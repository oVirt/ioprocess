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

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from ioprocess import IOProcess, ERR_IOPROCESS_CRASH, Timeout
from threading import Thread
import time
import errno
from tempfile import mkstemp, mkdtemp
import os
import shutil
from unittest import TestCase
import logging
from unittest.case import SkipTest
from functools import wraps
from weakref import ref
import gc
import pprint


elapsed_time = lambda: os.times()[4]

IOProcess.IOPROCESS_EXE = os.path.join(os.getcwd(),
                                       "../../src/ioprocess")
IOProcess._DEBUG_VALGRIND = os.environ.get("ENABLE_VALGRIND", False)

_VALGRIND_RUNNING = IOProcess._DEBUG_VALGRIND

IOProcess._TRACE_DEBUGGING = True


def skip_in_valgrind(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if _VALGRIND_RUNNING:
            raise SkipTest("Tests can't be run in valgrind")

        return f(*args, **kwargs)

    return wrapper


class IOProcessTests(TestCase):
    def setUp(self):
        self.log = logging.getLogger(self.__class__.__name__)
        self.proc = IOProcess(timeout=1, max_threads=5)

    def testMaxRequests(self):
        self.proc = IOProcess(timeout=5, max_threads=1, max_queued_requests=1)
        t1 = Thread(target=self.proc.echo, args=("hello", 2))
        t2 = Thread(target=self.proc.echo, args=("hello", 2))
        t1.start()
        t2.start()
        # Make sure the echo calls are sent prior to the ping otherwise one of
        # them would fail and ping() would pass
        time.sleep(0.5)

        try:
            self.proc.ping()
        except OSError as e:
            self.assertEquals(e.errno, errno.EAGAIN)
        except:
            self.fail("Expected OSError got %s", type(e))
        else:
            self.fail("Expected exception")
        finally:
            t1.join()
            t2.join()

    def testMaxRequestsAfterFillingThreadPool(self):
        self.proc = IOProcess(timeout=5, max_threads=3, max_queued_requests=0)
        t1 = Thread(target=self.proc.echo, args=("hello", 2))
        t2 = Thread(target=self.proc.echo, args=("hello", 2))
        t3 = Thread(target=self.proc.echo, args=("hello", 2))
        t1.start()
        t2.start()
        t3.start()

        for t in (t1, t2, t3):
            t.join()

        t1 = Thread(target=self.proc.echo, args=("hello", 2))
        t2 = Thread(target=self.proc.echo, args=("hello", 2))
        t1.start()
        t2.start()
        # Make sure the echo calls are sent prior to the ping otherwise one of
        # them would fail and ping() would pass
        time.sleep(0.5)
        self.proc.ping()
        t1.join()
        t2.join()

    def testPing(self):
        self.assertEquals(self.proc.ping(), "pong")

    def test2SubsequentCalls(self):
        self.assertEquals(self.proc.ping(), "pong")
        self.assertEquals(self.proc.ping(), "pong")

    def testEcho(self):
        data = """The Doctor: But I don't exist in your world!
                  Brigade Leader: Then you won't feel the bullets when we
                  shoot you."""  # (C) BBC - Doctor Who

        self.assertEquals(self.proc.echo(data), data)

    def testUnicodeEcho(self):
        data = u'\u05e9\u05dc\u05d5\u05dd'
        self.assertEquals(self.proc.echo(data), data)

    def testMultitask(self):
        """
        Makes sure that when multiple requests are sent the results come
        back with correct IDs
        """

        threadnum = 10
        self.proc.timeout = threadnum + 2
        errors = []
        threads = []

        def test(n):
            if self.proc.echo(str(n), n) != str(n):
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
        self.assertEquals(self.proc.echo(data), data)
        self.assertTrue(self.proc.crash())
        self.assertEquals(self.proc.echo(data), data)

    def testPendingRequestInvalidationOnCrash(self):
        data = """The Doctor: A straight line may be the shortest distance
                  between two points, but it is by no means the most
                  interesting."""  # (C) BBC - Doctor Who

        res = [False]
        self.proc.timeout = 12

        def sendCmd():
            try:
                self.proc.echo(data, 10)
            except OSError as e:
                if e.errno == ERR_IOPROCESS_CRASH:
                    res[0] = True
                else:
                    self.log.error("Got unexpected error", exc_info=True)

        t = Thread(target=sendCmd)
        t.start()

        time.sleep(1)
        self.proc.crash()
        t.join()
        self.assertTrue(res[0])

    def testTimeout(self):
        self.proc.timeout = 1
        data = """Madge: Are you the new caretaker?
                  The Doctor: Usually called "The Doctor." Or "The Caretaker."
                  Or "Get off this planet." Though, strictly speaking, that
                  probably isn't a name."""  # (C) BBC - Doctor Who

        try:
            self.assertEquals(self.proc.echo(data, 10), data)
        except Timeout:
            return

        self.fail("Exception not raised")

    @skip_in_valgrind
    def testManyRequests(self):
        self.proc.timeout = 30
        # even though we theoretically go back to a stable state, some objects
        # might have increased their internal buffers and mem fragmantation
        # might have caused some data to be spanned on more pages then it
        # originally did.
        acceptableRSSIncreasKB = 100
        data = """Lily: What's happening?
                  The Doctor: No idea. Just do what I do: hold tight and
                  pretend it's a plan."""  # (C) BBC - Doctor Who

        startRSS = self.proc.memstat()['rss']
        # This way we catch evey leak that is more then one 0.1KB per call
        many = 300
        for i in range(many):
            self.assertEquals(self.proc.echo(data), data)
        endRSS = self.proc.memstat()['rss']
        RSSDiff = endRSS - startRSS
        self.log.debug("RSS difference was %d KB, %d per request", RSSDiff,
                       RSSDiff / many)
        # This only tests for leaks in the main request\response process.
        self.assertTrue(RSSDiff < acceptableRSSIncreasKB,
                        "Detected a leak sized %d KB" % RSSDiff)

    def testStat(self):
        data = """The Doctor: [to Craig's baby] No! He's your dad! You can't
                              just call him "Not Mum".
                  Craig: "Not Mum"?
                  The Doctor: That's you! "Also Not Mum", that's me! And every
                              body else is [gets near to hear baby]
                              "Peasants"! That's a bit unfortunate...
                """  # (C) BBC - Doctor Who

        fd, path = mkstemp()
        try:
            os.write(fd, data)
            os.close(fd)
            pystat = os.stat(path)
            mystat = self.proc.stat(path)
            for f in mystat._fields:
                if f in ("st_atime", "st_mtime", "st_ctime"):
                    # These are float\double values and due to the many
                    # conversion the values experience during marshaling they
                    # cannot be equated. The rest of the fields are a good
                    # enough test.
                    continue

                self.log.debug("Testing field '%s'", f)
                self.assertEquals(getattr(mystat, f), getattr(pystat, f))
        finally:
            os.unlink(path)

    def testStatvfs(self):
        data = """Peter Puppy: Once again, evil is as rotting meat before
                               the maggots of justice!
                  Earthworm Jim: Thank you for cramming that delightful image
                                 into my brain, Peter.
                """  # (C) Universal Cartoon Studios - Earth Worm Jim

        fd, path = mkstemp()
        try:
            os.write(fd, data)
            os.close(fd)
            pystat = os.statvfs(path)
            mystat = self.proc.statvfs(path)
            for f in ("f_bsize", "f_frsize", "f_blocks",
                      "f_fsid", "f_flag", "f_namemax"):

                try:
                    getattr(pystat, f)
                except AttributeError:
                    # The results might be more comprehansive then python
                    # implementation
                    continue

                self.log.debug("Testing field '%s'", f)
                self.assertEquals(getattr(mystat, f), getattr(pystat, f))
        finally:
            os.unlink(path)

    def testStatFail(self):
        try:
            self.proc.stat("/I do not exist")
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise

    def testMissingArguemt(self):
        try:
            self.proc._sendCommand("echo", {}, self.proc.timeout)
        except OSError as e:
            self.assertEquals(e.errno, errno.EINVAL)

    def testNonExistingMethod(self):
        try:
            self.proc._sendCommand("Implode", {}, self.proc.timeout)
        except OSError as e:
            self.assertEquals(e.errno, errno.EINVAL)

    def testPathExists(self):
        fd, path = mkstemp()
        try:
            os.close(fd)
            self.assertTrue(self.proc.pathExists(path))
        finally:
            os.unlink(path)

    def testPathExistsFail(self):
        try:
            self.proc.pathExists("/I do not exist")
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise

    def testRename(self):
        fd, oldpath = mkstemp()
        newpath = oldpath + ".new"
        try:
            os.close(fd)
            self.assertTrue(self.proc.rename(oldpath, newpath))
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
        try:
            self.proc.rename("/I/do/not/exist", "/Dsadsad")
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise

    def testUnlink(self):
        fd, path = mkstemp()
        try:
            os.close(fd)
            self.assertTrue(self.proc.unlink(path))
        finally:
            try:
                os.unlink(path)
            except:
                pass

    def testUnlinkFail(self):
        try:
            self.proc.unlink("/I do not exist")
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise

    def testLink(self):
        fd, oldpath = mkstemp()
        newpath = oldpath + ".new"
        try:
            os.close(fd)
            self.assertTrue(self.proc.link(oldpath, newpath))
        finally:
            os.unlink(oldpath)
            try:
                os.unlink(newpath)
            except:
                pass

    def testLinkFail(self):
        try:
            self.proc.link("/I/do/not/exist", "/Dsadsad")
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise

    def testSymlink(self):
        fd, oldpath = mkstemp()
        newpath = oldpath + ".new"
        try:
            os.close(fd)
            self.assertTrue(self.proc.symlink(oldpath, newpath))
            self.assertEquals(os.path.realpath(newpath),
                              os.path.normpath(oldpath))
        finally:
            os.unlink(oldpath)
            try:
                os.unlink(newpath)
            except:
                pass

    def testSymlinkFail(self):
        try:
            self.proc.symlink("/I/do/not/exist", "/Dsadsad")
        except OSError as e:
            if e.errno != errno.EACCES:
                raise

    def testChmod(self):
        fd, path = mkstemp()
        targetMode = os.W_OK | os.R_OK
        try:
            os.chmod(path, 0)
            os.close(fd)
            self.assertFalse(os.stat(path).st_mode & targetMode)
            self.assertTrue(self.proc.chmod(path, targetMode))
            self.assertTrue(os.stat(path).st_mode & targetMode)
        finally:
            os.unlink(path)

    def testAccess(self):
        fd, path = mkstemp()
        try:
            os.close(fd)
            self.assertTrue(self.proc.access(path, os.W_OK))
        finally:
            os.unlink(path)

    def testChmodFail(self):
        try:
            self.proc.chmod("/I/do/not/exist", 0)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise

    def testReadfile(self, direct=False):

        data = """The Doctor: Well... you could do that. Yeah, you could do
                  that. Of course you could! But why? Look at these people,
                  these human beings. Consider their potential! From the day
                  they arrive on the planet, blinking, step into the sun,
                  there is more to see than can ever be seen, more to do
                  than-no, hold on. Sorry, that's The Lion King.
                  But the point still stands: leave them alone!
                  """  # (C) BBC - Doctor Who

        fd, path = mkstemp(dir="/var/tmp")
        try:
            os.write(fd, data)
            os.close(fd)
            remoteData = self.proc.readfile(path, direct)
            self.assertEquals(remoteData[:len(data)], data)
        finally:
            os.unlink(path)

    def testReadfileWithDirectIO(self):
        return self.testReadfile(True)

    def testWritefile(self, direct=False):
        data = """Jackie: I'm in my dressing gown.
                  The Doctor: Yes, you are.
                  Jackie: There's a strange man in my bedroom.
                  The Doctor: Yes, there is.
                  Jackie: Anything could happen.
                  The Doctor: No. [walks away]"""  # (C) BBC - Doctor Who

        fd, path = mkstemp(dir="/var/tmp")
        try:
            os.close(fd)
            self.proc.writefile(path, data, direct)
            with open(path, "r") as f:
                diskData = f.read()

            self.assertEquals(diskData[:len(data)], data)
        finally:
            os.unlink(path)

    def testWritefileWithDirectIO(self):
        return self.testWritefile(True)

    def testListdir(self):
        path = mkdtemp()
        matches = []
        for i in range(10):
            matches.append(os.path.join(path, str(i)))
            with open(matches[-1], "w") as f:
                f.write("A")

        matches.sort()

        try:
            remoteMatches = self.proc.listdir(path)
            remoteMatches.sort()
            flist = os.listdir(path)
            flist.sort()
            self.assertEquals(remoteMatches, flist)
        finally:
            shutil.rmtree(path)

    def testGlob(self):
        path = mkdtemp()
        matches = []
        for i in range(10):
            matches.append(os.path.join(path, str(i)))
            with open(matches[-1], "w") as f:
                f.write("A")

        matches.sort()

        try:
            remoteMatches = self.proc.glob(os.path.join(path, "*"))
            remoteMatches.sort()
            self.assertEquals(remoteMatches, matches)
        finally:
            shutil.rmtree(path)

    def testRmdir(self):
        path = mkdtemp()

        try:
            self.proc.rmdir(path)
            self.assertFalse(os.path.exists(path))
        finally:
            try:
                shutil.rmtree(path)
            except:
                pass

    def testMkdir(self):
        path = mkdtemp()
        shutil.rmtree(path)

        try:
            self.proc.mkdir(path)
            self.assertTrue(os.path.exists(path))
        finally:
            try:
                shutil.rmtree(path)
            except:
                pass

    def testLexists(self):
        path = "/tmp/linktest.ioprocesstest"
        try:
            os.unlink(path)
        except OSError:
            pass

        os.symlink("dsadsadsadsad", path)
        try:
            self.assertTrue(self.proc.lexists(path))
        finally:
            os.unlink(path)

    def testGlobNothing(self):
        remoteMatches = self.proc.glob(os.path.join("/dsadasd", "*"))
        self.assertEquals(remoteMatches, [])

    def testCircularRefs(self):
        """Make sure there is nothing keepin IOProcess strongly referenced.

        Since there is a comminucation background thread doing all the hard
        work we need to make sure it doesn't prevent IOProcess from being
        garbage collected.
        """
        proc = IOProcess(timeout=1, max_threads=5)
        proc = ref(proc)

        max_wait = 10
        end = elapsed_time() + max_wait

        while True:
            gc.collect()
            try:
                self.assertIsNone(proc())
            except AssertionError:
                refs = gc.get_referrers(proc())
                self.log.info(pprint.pformat(refs))
                if hasattr(refs[0], "f_code"):
                    self.log.info(pprint.pformat(refs[0].f_code))
                del refs

                if (elapsed_time() > end):
                    raise
            else:
                break

            time.sleep(1)

    def tearDown(self):
        self.proc.close()
