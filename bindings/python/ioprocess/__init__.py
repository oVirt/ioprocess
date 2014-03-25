import os
from select import poll, \
    POLLERR, POLLHUP, POLLPRI, POLLOUT, POLLIN, POLLWRBAND, \
    error
from threading import Thread, Event
from Queue import Queue, Empty
import fcntl
import json
from struct import Struct
import logging
import errno
from collections import namedtuple
from base64 import b64decode, b64encode
import stat
import time
import signal

from cpopen import CPopen

EXT_IOPROCESS = "/usr/libexec/ioprocess"

Size = Struct("@Q")

ARGTYPE_STRING = 1
ARGTYPE_NUMBER = 2

ERROR_FLAGS = POLLERR | POLLHUP
INPUT_READY_FLAGS = POLLIN | POLLPRI | ERROR_FLAGS
OUTPUT_READY_FLAGS = POLLOUT | POLLWRBAND | ERROR_FLAGS

ERR_IOPROCESS_CRASH = 100001

StatResult = namedtuple("StatResult", "st_mode, st_ino, st_dev, st_nlink,"
                                      "st_uid, st_gid, st_size, st_atime,"
                                      "st_mtime, st_ctime")

StatvfsResult = namedtuple("StatvfsResult", "f_bsize, f_frsize, f_blocks,"
                                            "f_bfree, f_bavail, f_files,"
                                            "f_ffree, f_favail, f_fsid,"
                                            "f_flag, f_namemax")

DEFAULT_MKDIR_MODE = (stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR |
                      stat.S_IRGRP | stat.S_IWGRP | stat.S_IXGRP |
                      stat.S_IROTH | stat.S_IXOTH)


def dict2namedtuple(d, ntType):
    return ntType(*[d[field] for field in ntType._fields])


def NoIntrPoll(pollfun, timeout=-1):
    """
    This wrapper is used to handle the interrupt exceptions that might
    occur during a poll system call. The wrapped function must be defined
    as poll([timeout]) where the special timeout value 0 is used to return
    immediately and -1 is used to wait indefinitely.
    """
    # When the timeout < 0 we shouldn't compute a new timeout after an
    # interruption.
    endtime = None if timeout < 0 else time.time() + timeout

    while True:
        try:
            return pollfun(timeout)
        except (IOError, error) as e:
            if e.args[0] != errno.EINTR:
                raise

        if endtime is not None:
            timeout = max(0, endtime - time.time())


class Timeout(RuntimeError):
    pass


def setNonBlocking(fd):
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)


class CmdResult(object):
    def __init__(self):
        self.event = Event()
        self.result = None


class DataSender(object):
    def __init__(self, fd, data):
        self._fd = fd
        self._dataPending = data

    def process(self):
        if not self._dataPending:
            return True

        n = os.write(self._fd, self._dataPending)
        self._dataPending = self._dataPending[n:]
        return False


class ResponseReader(object):
    def __init__(self, fd):
        self._fd = fd
        self._responses = []
        self._dataRemaining = 0
        self._dataBuffer = ""
        self.timeout = 10

    def process(self):
        if self._dataRemaining == 0:
            self._dataRemaining = Size.unpack(os.read(self._fd, Size.size))[0]

        while True:
            try:
                buff = os.read(self._fd, self._dataRemaining)
                break
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EINTR):
                    continue

                raise

        self._dataRemaining -= len(buff)
        self._dataBuffer += buff
        if self._dataRemaining == 0:
            resObj = json.loads(self._dataBuffer)
            self._responses.append(resObj)
            self._dataBuffer = ""
            return True

        return False

    def pop(self):
        return self._responses.pop()


class IOProcess(object):
    IOPROCESS_EXE = EXT_IOPROCESS
    _DEBUG_VALGRIND = False

    _log = logging.getLogger("IOProcessClient")
    _sublog = logging.getLogger("IOProcess")

    def __init__(self, max_threads=0, timeout=60):
        self.timeout = timeout
        self._max_threads = max_threads
        self._commandQueue = Queue()
        self._eventFdReciever, self._eventFdSender = os.pipe()
        self._reqId = 0
        self._isRunning = True

        self._run()
        self._partialLogs = ""

    def _run(self):
        self._log.debug("Starting IOProcess...")
        myRead, hisWrite = os.pipe()
        hisRead, myWrite = os.pipe()

        self._partialLogs = ""
        cmd = [self.IOPROCESS_EXE,
               "--read-pipe-fd", str(hisRead),
               "--write-pipe-fd", str(hisWrite),
               "--max-threads", str(self._max_threads)]

        if self._DEBUG_VALGRIND:
            cmd = ["valgrind", "--log-file=ioprocess.valgrind.log",
                   "--leak-check=full", "--tool=memcheck"] + cmd + \
                  ["--keep-fds"]

        p = CPopen(cmd)

        os.close(hisRead)
        os.close(hisWrite)

        setNonBlocking(myRead)
        setNonBlocking(myWrite)

        self._startCommunication(p, myRead, myWrite)

    def _pingPoller(self):
        os.write(self._eventFdSender, "0")

    def _startCommunication(self, proc, readPipe, writePipe):
        self._commthread = Thread(target=self._communicate,
                                  args=(proc, readPipe, writePipe))
        self._commthread.setDaemon(True)
        self._commthread.start()

    def _getRequestId(self):
        self._reqId += 1
        return self._reqId

    def _requestToString(self, cmd, reqId):
        methodName, args = cmd
        reqDict = {'id': reqId,
                   'methodName': methodName,
                   'args': args}

        reqStr = json.dumps(reqDict)

        res = Size.pack(len(reqStr))
        res += reqStr

        return res

    def _processLogs(self, data):
        lines = (self._partialLogs + data).splitlines(True)
        for line in lines:
            if not line.endswith("\n"):
                self._partialLogs = line
                return

            try:
                level, message = line.strip().split("|", 1)
            except:
                continue

            if level == "ERROR":
                self._sublog.error(message)
            elif level == "WARNING":
                self._sublog.warning(message)
            elif level == "DEBUG":
                self._sublog.debug(message)
            elif level == "INFO":
                self._sublog.info(message)

    def _communicate(self, proc, readPipe, writePipe):

        dataSender = None
        pendingRequests = {}
        responseReader = ResponseReader(readPipe)

        out = proc.stdout.fileno()
        err = proc.stderr.fileno()

        poller = poll()

        # When closing the ioprocess there might be race for closing this fd
        # using a copy solves this
        try:
            try:
                evtReciever = os.dup(self._eventFdReciever)
            except OSError:
                evtReciever = -1
                return

            poller.register(out, INPUT_READY_FLAGS)
            poller.register(err, INPUT_READY_FLAGS)
            poller.register(evtReciever, INPUT_READY_FLAGS)
            poller.register(readPipe, INPUT_READY_FLAGS)
            poller.register(writePipe, ERROR_FLAGS)

            while True:
                pollres = NoIntrPoll(poller.poll)
                if not self._isRunning:
                    self._log.info("shutdown requested")
                    break

                for fd, event in pollres:
                    if event & ERROR_FLAGS:
                        # If any FD closed something is wrong
                        # This is just to trigger the error flow
                        raise Exception("FD closed")

                    if fd in (out, err):
                        # TODO: logging
                        self._processLogs(os.read(fd, 1024))
                        continue

                    if fd == readPipe:
                        if not responseReader.process():
                            return

                        res = responseReader.pop()
                        reqId = res['id']
                        pendingReq = pendingRequests.get(reqId, None)
                        if pendingReq is not None:
                            pendingReq.result = res
                            pendingReq.event.set()
                        else:
                            self._log.warning("Unknown request id %d", reqId)

                        continue

                    if fd == evtReciever:
                        os.read(fd, 1)
                        if dataSender:
                            continue

                        try:
                            cmd, resObj = self._commandQueue.get_nowait()
                        except Empty:
                            continue

                        reqId = self._getRequestId()
                        pendingRequests[reqId] = resObj
                        reqString = self._requestToString(cmd, reqId)
                        dataSender = DataSender(writePipe, reqString)
                        poller.modify(writePipe, OUTPUT_READY_FLAGS)
                        continue

                    if fd == writePipe:
                        if dataSender.process():
                            dataSender = None
                            poller.modify(writePipe, ERROR_FLAGS)
                            self._pingPoller()
        except:
            self._log.error("IOProcess failure", exc_info=True)
            for request in pendingRequests.itervalues():
                request.result = {"errcode": ERR_IOPROCESS_CRASH,
                                  "errstr": "ioprocess crashed unexpectedly"}
                request.event.set()

        finally:
            os.close(readPipe)
            os.close(writePipe)
            if (evtReciever >= 0):
                os.close(evtReciever)

            if self._DEBUG_VALGRIND:
                os.kill(proc.pid, signal.SIGTERM)
                proc.wait()
            else:
                proc.kill()
            Thread(target=proc.wait).start()

            if self._isRunning:
                self._run()

    def _sendCommand(self, cmdName, args, timeout=None):
        res = CmdResult()
        self._commandQueue.put(((cmdName, args), res))
        self._pingPoller()
        res.event.wait(timeout)
        if not res.event.isSet():
            raise Timeout(os.strerror(errno.ETIMEDOUT))

        if res.result.get('errcode', 0) != 0:
            errcode = res.result['errcode']
            errstr = res.result.get('errstr', os.strerror(errcode))

            raise OSError(errcode, errstr)

        return res.result.get('result', None)

    def ping(self):
        return self._sendCommand("ping", {}, self.timeout)

    def echo(self, text, sleep=0):
        return self._sendCommand("echo",
                                 {'text': text, "sleep": sleep},
                                 self.timeout)

    def crash(self):
        try:
            self._sendCommand("crash", {}, self.timeout)
            return False
        except OSError as e:
            if e.errno == ERR_IOPROCESS_CRASH:
                return True

            return False

    def stat(self, path):
        resdict = self._sendCommand("stat", {"path": path}, self.timeout)
        return dict2namedtuple(resdict, StatResult)

    def statvfs(self, path):
        resdict = self._sendCommand("statvfs", {"path": path}, self.timeout)
        return dict2namedtuple(resdict, StatvfsResult)

    def pathExists(self, filename, writable=False):
        check = os.R_OK

        if writable:
            check |= os.W_OK

        if self.access(filename, check):
            return True

        return self.access(filename, check)

    def lexists(self, path):
        return self._sendCommand("lexists", {"path": path}, self.timeout)

    def fsyncPath(self, path):
        return self._sendCommand("lexists", {"path": path}, self.timeout)

    def access(self, path, mode):
        try:
            return self._sendCommand("access", {"path": path, "mode": mode},
                                     self.timeout)

        except OSError:
            #This is how python implements access
            return False

    def mkdir(self, path, mode=DEFAULT_MKDIR_MODE):
        return self._sendCommand("mkdir", {"path": path, "mode": mode},
                                 self.timeout)

    def listdir(self, path):
        return self._sendCommand("listdir", {"path": path}, self.timeout)

    # TODO: make test
    def truncate(self, path, length):
        return self._sendCommand("access", {"path": path, "length": length},
                                 self.timeout)

    def unlink(self, path):
        return self._sendCommand("unlink", {"path": path}, self.timeout)

    def rmdir(self, path):
        return self._sendCommand("rmdir", {"path": path}, self.timeout)

    def rename(self, oldpath, newpath):
        return self._sendCommand("rename",
                                 {"oldpath": oldpath,
                                  "newpath": newpath}, self.timeout)

    def link(self, oldpath, newpath):
        return self._sendCommand("link",
                                 {"oldpath": oldpath,
                                  "newpath": newpath}, self.timeout)

    def symlink(self, oldpath, newpath):
        return self._sendCommand("symlink",
                                 {"oldpath": oldpath,
                                  "newpath": newpath}, self.timeout)

    def chmod(self, path, mode):
        return self._sendCommand("chmod",
                                 {"path": path, "mode": mode}, self.timeout)

    def readfile(self, path, direct=False):
        b64result = self._sendCommand("readfile",
                                      {"path": path,
                                       "direct": direct}, self.timeout)

        return b64decode(b64result)

    def writefile(self, path, data, direct=False):
        self._sendCommand("writefile",
                          {"path": path,
                           "data": b64encode(data),
                           "direct": direct},
                          self.timeout)

    def readlines(self, path, direct=False):
        return self.readfile(path, direct).splitlines()

    def memstat(self):
        return self._sendCommand("memstat", {}, self.timeout)

    def glob(self, pattern):
        return self._sendCommand("glob", {"pattern": pattern}, self.timeout)

    def close(self, sync=True):
        if not self._isRunning:
            return

        self._isRunning = False

        self._pingPoller()
        os.close(self._eventFdReciever)
        os.close(self._eventFdSender)
        if sync:
            self._commthread.join()

    def __del__(self):
        self.close(False)
