#
# Copyright 2012 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301 USA
#
# Refer to the README and COPYING files for full details of the license
#

import errno
import gc
import logging
import os
import os
import pprint
import shutil
import subprocess
import time

from contextlib import closing
from functools import wraps
from tempfile import mkstemp, mkdtemp
from threading import Thread
from unittest import TestCase
from unittest.case import SkipTest
from weakref import ref

from ioprocess import IOProcess, ERR_IOPROCESS_CRASH, Closed, Timeout, config

elapsed_time = lambda: os.times()[4]

config.IOPROCESS_PATH = os.path.join(os.getcwd(),
                                     "../../src/ioprocess")
IOProcess._DEBUG_VALGRIND = os.environ.get("ENABLE_VALGRIND", False)

_VALGRIND_RUNNING = IOProcess._DEBUG_VALGRIND

IOProcess._TRACE_DEBUGGING = True


log = logging.getLogger("Test")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)-7s (%(threadName)s) [%(name)s] %(message)s"
)


def skip_in_valgrind(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if _VALGRIND_RUNNING:
            raise SkipTest("Tests can't be run in valgrind")

        return f(*args, **kwargs)

    return wrapper


class IOProcessTests(TestCase):

    def testMaxRequests(self):
        proc = IOProcess(timeout=5, max_threads=1, max_queued_requests=1)
        with closing(proc):
            t1 = Thread(target=proc.echo, args=("hello", 2))
            t2 = Thread(target=proc.echo, args=("hello", 2))
            t1.start()
            t2.start()
            # Make sure the echo calls are sent prior to the ping otherwise one
            # of them would fail and ping() would pass
            time.sleep(0.5)

            try:
                proc.ping()
            except OSError as e:
                self.assertEquals(e.errno, errno.EAGAIN)
            except Exception:
                self.fail("Expected OSError got %s", e)
            else:
                self.fail("Expected exception")
            finally:
                t1.join()
                t2.join()

    def testMaxRequestsAfterFillingThreadPool(self):
        proc = IOProcess(timeout=5, max_threads=3, max_queued_requests=0)
        with closing(proc):
            t1 = Thread(target=proc.echo, args=("hello", 2))
            t2 = Thread(target=proc.echo, args=("hello", 2))
            t3 = Thread(target=proc.echo, args=("hello", 2))
            t1.start()
            t2.start()
            t3.start()

            for t in (t1, t2, t3):
                t.join()

            t1 = Thread(target=proc.echo, args=("hello", 2))
            t2 = Thread(target=proc.echo, args=("hello", 2))
            t1.start()
            t2.start()
            # Make sure the echo calls are sent prior to the ping otherwise one
            # of them would fail and ping() would pass
            time.sleep(0.5)
            proc.ping()
            t1.join()
            t2.join()

    def testPing(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            self.assertEquals(proc.ping(), "pong")

    def test2SubsequentCalls(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            self.assertEquals(proc.ping(), "pong")
            self.assertEquals(proc.ping(), "pong")

    def testEcho(self):
        data = """The Doctor: But I don't exist in your world!
                  Brigade Leader: Then you won't feel the bullets when we
                  shoot you."""  # (C) BBC - Doctor Who
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            self.assertEquals(proc.echo(data), data)

    def testUnicodeEcho(self):
        data = u'\u05e9\u05dc\u05d5\u05dd'
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            self.assertEquals(proc.echo(data), data)

    def testMultitask(self):
        """
        Makes sure that when multiple requests are sent the results come
        back with correct IDs
        """
        threadnum = 10
        # We want to run all requests in parallel, so have one ioprocess thread
        # per client thread.
        proc = IOProcess(timeout=2, max_threads=threadnum)
        with closing(proc):
            errors = []
            threads = []

            def test(n):
                if proc.echo(str(n), 1) != str(n):
                    errors.append(n)

        for i in range(threadnum):
            t = Thread(target=test, args=(i,))
            t.start()
            threads.append(t)

        for thread in threads:
            thread.join()

        self.assertEquals(len(errors), 0)

    def testRecoverAfterCrash(self):
        data = """Brigadier: Is there anything I can do?
                  Third Doctor: Yes, pass me a silicon rod.
                                [Stirs cup of tea with it]
                  Brigadier: I meant is there anything UNIT can do about this
                  space lightning business?"""  # (C) BBC - Doctor Who
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            self.assertEquals(proc.echo(data), data)
            self.assertTrue(proc.crash())
            self.assertEquals(proc.echo(data), data)

    def testPendingRequestInvalidationOnCrash(self):
        data = """The Doctor: A straight line may be the shortest distance
                  between two points, but it is by no means the most
                  interesting."""  # (C) BBC - Doctor Who
        proc = IOProcess(timeout=12, max_threads=5)
        with closing(proc):
            res = [False]

            def sendCmd():
                try:
                    proc.echo(data, 10)
                except OSError as e:
                    if e.errno == ERR_IOPROCESS_CRASH:
                        res[0] = True
                    else:
                        log.error("Got unexpected error", exc_info=True)

            t = Thread(target=sendCmd)
            t.start()

            time.sleep(1)
            proc.crash()
            t.join()
            self.assertTrue(res[0])

    def testTimeout(self):
        data = """Madge: Are you the new caretaker?
                  The Doctor: Usually called "The Doctor." Or "The Caretaker."
                  Or "Get off this planet." Though, strictly speaking, that
                  probably isn't a name."""  # (C) BBC - Doctor Who
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            try:
                self.assertEquals(proc.echo(data, 10), data)
            except Timeout:
                return

            self.fail("Exception not raised")

    @skip_in_valgrind
    def testManyRequests(self):
        data = """Lily: What's happening?
                  The Doctor: No idea. Just do what I do: hold tight and
                  pretend it's a plan."""  # (C) BBC - Doctor Who
        proc = IOProcess(timeout=30, max_threads=5)
        with closing(proc):
            # even though we theoretically go back to a stable state, some
            # objects might have increased their internal buffers and mem
            # fragmantation might have caused some data to be spanned on more
            # pages then it originally did.
            acceptableRSSIncreasKB = 100

            startRSS = proc.memstat()['rss']
            # This way we catch evey leak that is more then one 0.1KB per call
            many = 300
            for i in range(many):
                self.assertEquals(proc.echo(data), data)
            endRSS = proc.memstat()['rss']
            RSSDiff = endRSS - startRSS
            log.debug("RSS difference was %d KB, %d per request", RSSDiff,
                      RSSDiff / many)
            # This only tests for leaks in the main request\response process.
            self.assertTrue(RSSDiff < acceptableRSSIncreasKB,
                            "Detected a leak sized %d KB" % RSSDiff)

    def testStat(self):
        data = b'''The Doctor: [to Craig's baby] No! He's your dad! You can't
                               just call him "Not Mum".
                   Craig: "Not Mum"?
                   The Doctor: That's you! "Also Not Mum", that's me! And every
                               body else is [gets near to hear baby]
                               "Peasants"! That's a bit unfortunate...
                 '''  # (C) BBC - Doctor Who
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            fd, path = mkstemp()
            try:
                os.write(fd, data)
                os.close(fd)
                pystat = os.stat(path)
                mystat = proc.stat(path)
                for f in mystat._fields:
                    if f in ("st_atime", "st_mtime", "st_ctime"):
                        # These are float\double values and due to the many
                        # conversion the values experience during marshaling
                        # they cannot be equated. The rest of the fields are a
                        # good enough test.
                        continue

                    log.debug("Testing field '%s'", f)
                    self.assertEquals(getattr(mystat, f), getattr(pystat, f))
            finally:
                os.unlink(path)

    def testStatvfs(self):
        data = b'''Peter Puppy: Once again, evil is as rotting meat before
                                the maggots of justice!
                   Earthworm Jim: Thank you for cramming that delightful image
                                  into my brain, Peter.
                '''  # (C) Universal Cartoon Studios - Earth Worm Jim
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            fd, path = mkstemp()
            try:
                os.write(fd, data)
                os.close(fd)
                pystat = os.statvfs(path)
                mystat = proc.statvfs(path)
                for f in ("f_bsize", "f_frsize", "f_blocks",
                          "f_fsid", "f_flag", "f_namemax"):

                    try:
                        getattr(pystat, f)
                    except AttributeError:
                        # The results might be more comprehansive then python
                        # implementation
                        continue

                    log.debug("Testing field '%s'", f)
                    self.assertEquals(getattr(mystat, f), getattr(pystat, f))
            finally:
                os.unlink(path)

    def testStatFail(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            try:
                proc.stat("/I do not exist")
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise
            else:
                raise AssertionError("OSError was not raised")

    def testMissingArguemt(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            try:
                proc._sendCommand("echo", {}, proc.timeout)
            except OSError as e:
                self.assertEquals(e.errno, errno.EINVAL)

    def testNonExistingMethod(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            try:
                proc._sendCommand("Implode", {}, proc.timeout)
            except OSError as e:
                self.assertEquals(e.errno, errno.EINVAL)

    def testPathExists(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            fd, path = mkstemp()
            try:
                os.close(fd)
                self.assertTrue(proc.pathExists(path))
            finally:
                os.unlink(path)

    def testPathDoesNotExist(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            self.assertFalse(proc.pathExists("/I do not exist"))

    def testRename(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            fd, oldpath = mkstemp()
            newpath = oldpath + ".new"
            try:
                os.close(fd)
                self.assertTrue(proc.rename(oldpath, newpath))
            finally:
                try:
                    os.unlink(oldpath)
                except:
                    pass
                try:
                    os.unlink(newpath)
                except:
                    pass

    def testRenameFail(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            try:
                proc.rename("/I/do/not/exist", "/Dsadsad")
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise
            else:
                raise AssertionError("OSError was not raised")

    def testUnlink(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            fd, path = mkstemp()
            try:
                os.close(fd)
                self.assertTrue(proc.unlink(path))
            finally:
                try:
                    os.unlink(path)
                except:
                    pass

    def testUnlinkFail(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            try:
                proc.unlink("/I do not exist")
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise
            else:
                raise AssertionError("OSError was not raised")

    def testLink(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            fd, oldpath = mkstemp()
            newpath = oldpath + ".new"
            try:
                os.close(fd)
                self.assertTrue(proc.link(oldpath, newpath))
            finally:
                os.unlink(oldpath)
                try:
                    os.unlink(newpath)
                except:
                    pass

    def testLinkFail(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            try:
                proc.link("/I/do/not/exist", "/Dsadsad")
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise
            else:
                raise AssertionError("OSError was not raised")

    def testSymlink(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            fd, oldpath = mkstemp()
            newpath = oldpath + ".new"
            try:
                os.close(fd)
                self.assertTrue(proc.symlink(oldpath, newpath))
                self.assertEquals(os.path.realpath(newpath),
                                  os.path.normpath(oldpath))
            finally:
                os.unlink(oldpath)
                try:
                    os.unlink(newpath)
                except:
                    pass

    def testSymlinkFail(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            try:
                proc.symlink("/Dsadsad", "/I/do/not/exist")
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise
            else:
                raise AssertionError("OSError was not raised")

    def testChmod(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            fd, path = mkstemp()
            targetMode = os.W_OK | os.R_OK
            try:
                os.chmod(path, 0)
                os.close(fd)
                self.assertFalse(os.stat(path).st_mode & targetMode)
                self.assertTrue(proc.chmod(path, targetMode))
                self.assertTrue(os.stat(path).st_mode & targetMode)
            finally:
                os.unlink(path)

    def testAccess(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            fd, path = mkstemp()
            try:
                os.close(fd)
                self.assertTrue(proc.access(path, os.W_OK))
            finally:
                os.unlink(path)

    def testChmodFail(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            try:
                proc.chmod("/I/do/not/exist", 0)
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise
            else:
                raise AssertionError("OSError was not raised")

    def testReadfile(self, direct=False):
        data = b'''The Doctor: Well... you could do that. Yeah, you could do
                   that. Of course you could! But why? Look at these people,
                   these human beings. Consider their potential! From the day
                   they arrive on the planet, blinking, step into the sun,
                   there is more to see than can ever be seen, more to do
                   than-no, hold on. Sorry, that's The Lion King.
                   But the point still stands: leave them alone!
                   '''  # (C) BBC - Doctor Who
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            fd, path = mkstemp(dir="/var/tmp")
            try:
                os.write(fd, data)
                os.close(fd)
                remoteData = proc.readfile(path, direct)
                self.assertEquals(remoteData[:len(data)], data)
            finally:
                os.unlink(path)

    def testReadfileWithDirectIO(self):
        return self.testReadfile(True)

    def testWritefile(self, direct=False):
        data = b'''Jackie: I'm in my dressing gown.
                   The Doctor: Yes, you are.
                   Jackie: There's a strange man in my bedroom.
                   The Doctor: Yes, there is.
                   Jackie: Anything could happen.
                   The Doctor: No. [walks away]'''  # (C) BBC - Doctor Who
        # This test sometimes time out in the CI. On one failure, the write
        # took 1.8 seconds inside ioprocess.
        proc = IOProcess(timeout=5, max_threads=5)
        with closing(proc):
            fd, path = mkstemp(dir="/var/tmp")
            try:
                os.close(fd)
                proc.writefile(path, data, direct)
                with open(path, 'rb') as f:
                    diskData = f.read()

                self.assertEquals(diskData[:len(data)], data)
            finally:
                os.unlink(path)

    def testWritefileWithDirectIO(self):
        return self.testWritefile(True)

    def testListdir(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            path = mkdtemp()
            matches = []
            for i in range(10):
                matches.append(os.path.join(path, str(i)))
                with open(matches[-1], "w") as f:
                    f.write("A")

            matches.sort()

            try:
                remoteMatches = proc.listdir(path)
                remoteMatches.sort()
                flist = os.listdir(path)
                flist.sort()
                self.assertEquals(remoteMatches, flist)
            finally:
                shutil.rmtree(path)

    def testGlob(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            path = mkdtemp()
            matches = []
            for i in range(10):
                matches.append(os.path.join(path, str(i)))
                with open(matches[-1], "w") as f:
                    f.write("A")

            matches.sort()

            try:
                remoteMatches = proc.glob(os.path.join(path, "*"))
                remoteMatches.sort()
                self.assertEquals(remoteMatches, matches)
            finally:
                shutil.rmtree(path)

    def testRmdir(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            path = mkdtemp()

            try:
                proc.rmdir(path)
                self.assertFalse(os.path.exists(path))
            finally:
                try:
                    shutil.rmtree(path)
                except:
                    pass

    def testMkdir(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            path = mkdtemp()
            shutil.rmtree(path)

            try:
                proc.mkdir(path)
                self.assertTrue(os.path.exists(path))
            finally:
                try:
                    shutil.rmtree(path)
                except:
                    pass

    def testLexists(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            path = "/tmp/linktest.ioprocesstest"
            try:
                os.unlink(path)
            except OSError:
                pass
            os.symlink("dsadsadsadsad", path)
            try:
                self.assertTrue(proc.lexists(path))
            finally:
                os.unlink(path)

    def testGlobNothing(self):
        proc = IOProcess(timeout=1, max_threads=5)
        with closing(proc):
            remoteMatches = proc.glob(os.path.join("/dsadasd", "*"))
            self.assertEquals(remoteMatches, [])

    def test_closed(self):
        proc = IOProcess(timeout=1, max_threads=5)
        proc.close()
        self.assertRaises(Closed, proc.echo, "foo", 1)


class TestWeakerf(TestCase):

    def test_close_when_unrefed(self):
        """Make sure there is nothing keepin IOProcess strongly referenced.

        Since there is a comminucation background thread doing all the hard
        work we need to make sure it doesn't prevent IOProcess from being
        garbage collected.
        """
        proc = IOProcess(timeout=1, max_threads=5)
        proc = ref(proc)

        end = elapsed_time() + 5.0

        while True:
            gc.collect()
            real_proc = proc()
            if real_proc is None:
                break
            refs = gc.get_referrers(real_proc)
            log.info("Object referencing ioprocess instance: %s",
                     pprint.pformat(refs))
            if hasattr(refs[0], "f_code"):
                log.info("Function referencing ioprocess instance: %s",
                         pprint.pformat(refs[0].f_code))
            if elapsed_time() > end:
                raise AssertionError("These objects still reference "
                                     "ioprocess: %s" % refs)
            del refs
            del real_proc
            time.sleep(0.1)


class FakeLogger(object):

    def __init__(self):
        self.messages = []

    def debug(self, fmt, *args):
        msg = fmt % args
        self.messages.append(msg)

    info = debug
    warning = debug
    error = debug


class LoggingTests(TestCase):

    def test_partial_logs(self):
        threads = []
        proc = IOProcess(timeout=1, max_threads=10)
        proc._sublog = FakeLogger()

        def worker():
            for i in range(100):
                proc.stat(__file__)

        try:
            for i in range(4):
                t = Thread(target=worker)
                t.deamon = True
                t.start()
                threads.append(t)
        finally:
            for t in threads:
                t.join()
            proc.close()

        for msg in proc._sublog.messages:
            self.assertFalse('DEBUG|' in msg,
                             "Raw log data in log message: %r" % msg)
