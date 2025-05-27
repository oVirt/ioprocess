import itertools
import os
import queue
from select import poll, \
    POLLERR, POLLHUP, POLLPRI, POLLOUT, POLLIN, POLLWRBAND, \
    error
from threading import Thread, Event, Lock, current_thread
import fcntl
import json
from struct import Struct
import logging
import errno
from collections import namedtuple
from base64 import b64decode, b64encode
import stat
import signal
from weakref import ref
import subprocess

try:
    from vdsm import pthread
except ImportError:
    pthread = None

elapsed_time = lambda: os.times()[4]  # The system's monotonic timer

from . import config

Size = Struct("@Q")

ARGTYPE_STRING = 1
ARGTYPE_NUMBER = 2

ERROR_FLAGS = POLLERR | POLLHUP
INPUT_READY_FLAGS = POLLIN | POLLPRI | ERROR_FLAGS
OUTPUT_READY_FLAGS = POLLOUT | POLLWRBAND | ERROR_FLAGS

ERR_IOPROCESS_CRASH = 100001

StatResult = namedtuple("StatResult", "st_mode, st_ino, st_dev, st_nlink,"
                                      "st_uid, st_gid, st_size, st_atime,"
                                      "st_mtime, st_ctime, st_blocks")

StatvfsResult = namedtuple("StatvfsResult", "f_bsize, f_frsize, f_blocks,"
                                            "f_bfree, f_bavail, f_files,"
                                            "f_ffree, f_favail, f_fsid,"
                                            "f_flag, f_namemax")

DEFAULT_MKDIR_MODE = (stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR |
                      stat.S_IRGRP | stat.S_IWGRP | stat.S_IXGRP |
                      stat.S_IROTH | stat.S_IXOTH)

_ANY_CPU = "0-%d" % (os.sysconf('SC_NPROCESSORS_CONF') - 1)


# Logger for IOProcessClient and communication thread. It is used outside of
# the IOProcessClient since the comunication thread does not have a reference
# to the client.
_log = logging.getLogger("IOProcessClient")


class PollError(Exception):
    msg = "Poll error {self.error} on fd {self.fd}"

    def __init__(self, fd, error):
        self.fd = fd
        self.error = error

    def __str__(self):
        return self.msg.format(self=self)


# Communicate is a function to prevent the bound method from strong referencing
# ioproc
def _communicate(ioproc_ref, proc, readPipe, writePipe):
    real_ioproc = ioproc_ref()
    if real_ioproc is None:
        return

    # Keeps the name for logging in this thread.
    ioproc_name = real_ioproc.name

    real_ioproc._started.set()

    dataSender = None
    pendingRequests = {}
    responseReader = ResponseReader(readPipe)

    err = proc.stderr.fileno()

    poller = poll()

    # When closing the ioprocess there might be race for closing this fd
    # using a copy solves this
    try:
        try:
            evtReciever = os.dup(real_ioproc._eventFdReciever)
        except OSError:
            evtReciever = -1
            return

        poller.register(err, INPUT_READY_FLAGS)
        poller.register(evtReciever, INPUT_READY_FLAGS)
        poller.register(readPipe, INPUT_READY_FLAGS)
        poller.register(writePipe, ERROR_FLAGS)

        while True:
            real_ioproc = None

            pollres = NoIntrPoll(poller.poll, 5)

            real_ioproc = ioproc_ref()
            if real_ioproc is None:
                break

            if not real_ioproc._isRunning:
                _log.info("(%s) Shutdown requested", ioproc_name)
                break

            for fd, event in pollres:
                if event & ERROR_FLAGS:
                    raise PollError(fd, event & ERROR_FLAGS)

                if fd == err:
                    real_ioproc._processLogs(os.read(fd, 1024))
                    continue

                if fd == readPipe:
                    if not responseReader.process():
                        continue

                    res = responseReader.pop()
                    reqId = res['id']
                    pendingReq = pendingRequests.pop(reqId, None)
                    if pendingReq is not None:
                        pendingReq.result = res
                        pendingReq.event.set()
                    else:
                        _log.warning("(%s) Unknown request id %d",
                                     ioproc_name, reqId)
                    continue

                if fd == evtReciever:
                    os.read(fd, 1)
                    if dataSender:
                        continue

                    try:
                        cmd, resObj = real_ioproc._commandQueue.get_nowait()
                    except queue.Empty:
                        continue

                    reqId = real_ioproc._getRequestId()
                    pendingRequests[reqId] = resObj
                    reqString = real_ioproc._requestToBytes(cmd, reqId)
                    dataSender = DataSender(writePipe, reqString)
                    poller.modify(writePipe, OUTPUT_READY_FLAGS)
                    continue

                if fd == writePipe:
                    if dataSender.process():
                        dataSender = None
                        poller.modify(writePipe, ERROR_FLAGS)
                        real_ioproc._pingPoller()
    except PollError as e:
        # Normal during shutdown - don't log an error.
        _log.info("(%s) %s", ioproc_name, e)
        _cleanup(pendingRequests)
    except:
        # Unexpected error.
        _log.exception("(%s) Communication thread failed", ioproc_name)
        _cleanup(pendingRequests)
    finally:
        os.close(readPipe)
        os.close(writePipe)
        if (evtReciever >= 0):
            os.close(evtReciever)

        rc = proc.poll()

        if rc is None:
            _log.info("(%s) Killing ioprocess", ioproc_name)
            if IOProcess._DEBUG_VALGRIND:
                os.kill(proc.pid, signal.SIGTERM)
            else:
                proc.kill()
            rc = proc.wait()

        if rc < 0:
            _log.info("(%s) ioprocess was terminated by signal %s",
                      ioproc_name, -rc)
        else:
            _log.info("(%s) ioprocess terminated with code %s",
                      ioproc_name, rc)

        real_ioproc = ioproc_ref()
        if real_ioproc is not None:
            with real_ioproc._lock:
                if real_ioproc._isRunning:
                    real_ioproc._run()


def _cleanup(pending):
    for request in pending.values():
        request.result = {"errcode": ERR_IOPROCESS_CRASH,
                          "errstr": "ioprocess crashed unexpectedly"}
        request.event.set()


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
    if timeout < 0:
        endtime = None
    else:
        endtime = elapsed_time() + timeout

    while True:
        try:
            return pollfun(timeout * 1000)  # timeout for poll is in ms
        except (IOError, error) as e:
            if e.args[0] != errno.EINTR:
                raise

        if endtime is not None and elapsed_time() > endtime:
            timeout = max(0, endtime - elapsed_time())


class Closed(RuntimeError):
    """ Raised when sending command to closed client """


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
        self._dataBuffer = b''
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
            resObj = json.loads(self._dataBuffer.decode('utf8'))
            self._responses.append(resObj)
            self._dataBuffer = b''
            return True

        return False

    def pop(self):
        return self._responses.pop()


class IOProcess(object):
    _DEBUG_VALGRIND = False
    _TRACE_DEBUGGING = False

    _sublog = logging.getLogger("IOProcess")
    _counter = itertools.count()

    def __init__(self, max_threads=0, timeout=60, max_queued_requests=-1,
                 name=None, wait_until_ready=2):
        self.timeout = timeout
        self._max_threads = max_threads
        self._max_queued_requests = max_queued_requests
        self._name = name or "ioprocess-%d" % next(self._counter)
        self._wait_until_ready = wait_until_ready
        self._commandQueue = queue.Queue()
        self._eventFdReciever, self._eventFdSender = os.pipe()
        self._reqId = 0
        self._isRunning = True
        self._started = Event()
        self._lock = Lock()
        self._partialLogs = ""
        self._pid = None

        _log.info("(%s) Starting client", self.name)
        self._run()

    @property
    def name(self):
        return self._name

    @property
    def pid(self):
        return self._pid

    def _run(self):
        _log.debug("(%s) Starting ioprocess", self.name)
        myRead, hisWrite = os.pipe()
        hisRead, myWrite = os.pipe()

        for fd in (hisRead, hisWrite):
            # Python 3 creates fds with the close-on-exec flag set.
            clear_cloexec(fd)

        self._partialLogs = ""

        cmd = [config.TASKSET_PATH,
               '--cpu-list', _ANY_CPU,
               config.IOPROCESS_PATH,
               "--read-pipe-fd", str(hisRead),
               "--write-pipe-fd", str(hisWrite),
               "--max-threads", str(self._max_threads),
               "--max-queued-requests", str(self._max_queued_requests),
               ]

        if self._TRACE_DEBUGGING:
            cmd.append("--trace-enabled")

        if self._DEBUG_VALGRIND:
            cmd = ["valgrind", "--log-file=ioprocess.valgrind.log",
                   "--leak-check=full", "--tool=memcheck"] + cmd + \
                  ["--keep-fds"]

        p = subprocess.Popen(
            cmd,
            pass_fds=(hisRead, hisWrite),
            stderr=subprocess.PIPE
        )

        self._pid = p.pid

        os.close(hisRead)
        os.close(hisWrite)

        setNonBlocking(myRead)
        setNonBlocking(myWrite)

        self._startCommunication(p, myRead, myWrite)

    def _pingPoller(self):
        try:
            os.write(self._eventFdSender, b'0')
        except OSError as e:
            if e.errno == errno.EAGAIN:
                return
            if not self._isRunning:
                raise Closed("Client %s was closed" % self.name)
            raise

    def _startCommunication(self, proc, readPipe, writePipe):
        _log.debug("(%s) Starting communication thread", self.name)
        self._started.clear()

        args = (ref(self), proc, readPipe, writePipe)
        self._commthread = start_thread(
            _communicate,
            args,
            name="ioprocess/%d" % (proc.pid,),
        )

        if self._started.wait(self._wait_until_ready):
            _log.debug("(%s) Communication thread started", self.name)
        else:
            _log.warning("(%s) Timeout waiting for communication thread",
                         self.name)

    def _getRequestId(self):
        self._reqId += 1
        return self._reqId

    def _requestToBytes(self, cmd, reqId):
        methodName, args = cmd
        reqDict = {'id': reqId,
                   'methodName': methodName,
                   'args': args}

        reqStr = json.dumps(reqDict)

        res = Size.pack(len(reqStr))
        res += reqStr.encode('utf8')

        return res

    def _processLogs(self, data):
        if self._partialLogs:
            data = self._partialLogs + data
            self._partialLogs = b''
        lines = data.splitlines(True)
        for line in lines:
            if not line.endswith(b"\n"):
                self._partialLogs = line
                return

            # We must decode the line becuase python3 does not log bytes
            # properly (e.g. you get "b'text'" intead of "text").
            line = line.decode('utf8', 'replace')
            try:
                level, logDomain, message = line.strip().split("|", 2)
            except:
                _log.warning("(%s) Invalid log message %r", self.name, line)
                continue

            if level == "ERROR":
                self._sublog.error("(%s) %s", self.name, message)
            elif level == "WARNING":
                self._sublog.warning("(%s) %s", self.name, message)
            elif level == "DEBUG":
                self._sublog.debug("(%s) %s", self.name, message)
            elif level == "INFO":
                self._sublog.info("(%s) %s", self.name, message)

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

    def lstat(self, path):
        resdict = self._sendCommand("lstat", {"path": path}, self.timeout)
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
        self._sendCommand("fsyncPath", {"path": path}, self.timeout)

    def access(self, path, mode):
        try:
            return self._sendCommand("access", {"path": path, "mode": mode},
                                     self.timeout)

        except OSError:
            # This is how python implements access
            return False

    def mkdir(self, path, mode=DEFAULT_MKDIR_MODE):
        return self._sendCommand("mkdir", {"path": path, "mode": mode},
                                 self.timeout)

    def listdir(self, path):
        return self._sendCommand("listdir", {"path": path}, self.timeout)

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
                           "data": b64encode(data).decode('utf8'),
                           "direct": direct},
                          self.timeout)

    def readlines(self, path, direct=False):
        return self.readfile(path, direct).splitlines()

    def memstat(self):
        return self._sendCommand("memstat", {}, self.timeout)

    def glob(self, pattern):
        return self._sendCommand("glob", {"pattern": pattern}, self.timeout)

    def touch(self, path, flags, mode):
        return self._sendCommand("touch",
                                 {"path": path,
                                  "flags": flags,
                                  "mode": mode},
                                 self.timeout)

    def truncate(self, path, size, mode, excl):
        return self._sendCommand("truncate",
                                 {"path": path,
                                  "size": size,
                                  "mode": mode,
                                  "excl": excl},
                                 self.timeout)

    def probe_block_size(self, dir_path):
        """
        Probe block size of the underling filesystem.

        ioprocess tries to create a temporary unnamed file in dir_path; but if
        the underlyng filesystem does not support the O_TMPFILE flag, a probe
        file (e.g. ".probe-adca9f57-08a8-40a0-9904-8acb10fd503d") may be left
        in the directory).

        Arguments:
            dir_path (str): path to directory to probe. ioprocess must have
                execute and write access to this directory.

        Return:
            The block size of the underlying filesystem. Value of 1 means the
            block size cannot be detected.

        Raises:
            OSError if the probing failed. Interesting errno values are:
            - EINVAL: the filesystem does not support direct I/O.
            - EEXIST: the probe file exists, caller may try again (unlikely)
            - ENOMEM: no memory (unlikely)
        """
        return self._sendCommand(
            "probe_block_size", {"dir": dir_path}, self.timeout)

    def close(self, sync=True):
        with self._lock:
            if not self._isRunning:
                return
            self._isRunning = False

        _log.info("(%s) Closing client", self.name)
        self._pingPoller()
        os.close(self._eventFdReciever)
        os.close(self._eventFdSender)
        if sync:
            _log.debug("(%s) Waiting for communication thread", self.name)
            self._commthread.join()

    def __del__(self):
        self.close(False)


def clear_cloexec(fd):
    """
    Make fd inheritable by a child process.
    """
    flags = fcntl.fcntl(fd, fcntl.F_GETFD)
    fcntl.fcntl(fd, fcntl.F_SETFD, flags & ~fcntl.FD_CLOEXEC)


def start_thread(func, args=(), name=None, daemon=True):

    def run():
        try:
            if pthread:
                thread_name = current_thread().name
                pthread.setname(thread_name[:15])
            return func(*args)
        except Exception:
            logging.exception("Unhandled error in thread %s", name)

    t = Thread(target=run, name=name)
    t.daemon = daemon
    t.start()
    return t
