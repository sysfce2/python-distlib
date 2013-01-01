from itertools import islice
import os
import shutil
import tempfile
import textwrap
import time

from compat import unittest

from distlib import DistlibException
from distlib.compat import cache_from_source
from distlib.util import (get_export_entry, ExportEntry, resolve,
                          get_cache_base, path_to_cache_dir,
                          parse_credentials, ensure_slash, split_filename,
                          EventMixin, Sequencer, unarchive, Progress,
                          FileOperator, is_string_sequence, get_package_data)

HERE = os.path.dirname(__file__)

class UtilTestCase(unittest.TestCase):
    def check_entry(self, entry, name, prefix, suffix, flags):
        self.assertEqual(entry.name, name)
        self.assertEqual(entry.prefix, prefix)
        self.assertEqual(entry.suffix, suffix)
        self.assertEqual(entry.flags, flags)

    def test_export_entry(self):
        self.assertIsNone(get_export_entry('foo.py'))
        self.assertIsNone(get_export_entry('foo.py='))
        for spec in ('foo=foo:main', 'foo =foo:main', 'foo= foo:main',
                     'foo = foo:main'):
            self.check_entry(get_export_entry(spec),
                             'foo', 'foo', 'main', [])
        self.check_entry(get_export_entry('foo=foo.bar:main'),
                         'foo', 'foo.bar', 'main', [])
        self.check_entry(get_export_entry('foo=foo.bar:main [a]'),
                         'foo', 'foo.bar', 'main', ['a'])
        self.check_entry(get_export_entry('foo=foo.bar:main [ a ]'),
                         'foo', 'foo.bar', 'main', ['a'])
        self.check_entry(get_export_entry('foo=foo.bar:main [a=b, c=d,e, f=g]'),
                         'foo', 'foo.bar', 'main', ['a=b', 'c=d', 'e', 'f=g'])
        self.check_entry(get_export_entry('foo=foo.bar:main [a=9, 9=8,e, f9=g8]'),
                         'foo', 'foo.bar', 'main', ['a=9', '9=8', 'e', 'f9=g8'])
        self.check_entry(get_export_entry('foo=foo.bar:main[x]'),
                         'foo', 'foo.bar', 'main', ['x'])
        self.check_entry(get_export_entry('foo=abc'), 'foo', 'abc', None, [])
        self.assertRaises(DistlibException, get_export_entry, 'foo=foo.bar:x:y')
        self.assertRaises(DistlibException, get_export_entry, 'foo=foo.bar:x [')
        self.assertRaises(DistlibException, get_export_entry, 'foo=foo.bar:x ]')
        self.assertRaises(DistlibException, get_export_entry, 'foo=foo.bar:x []')
        self.assertRaises(DistlibException, get_export_entry, 'foo=foo.bar:x [\]')
        self.assertRaises(DistlibException, get_export_entry, 'foo=foo.bar:x [a=]')
        self.assertRaises(DistlibException, get_export_entry, 'foo=foo.bar:x [a,]')
        self.assertRaises(DistlibException, get_export_entry, 'foo=foo.bar:x [a,,b]')
        self.assertRaises(DistlibException, get_export_entry, 'foo=foo.bar:x [a b]')

    def test_resolve(self):
        import logging
        import logging.handlers
        self.assertIs(resolve('logging', None), logging)
        self.assertIs(resolve('logging.handlers', None), logging.handlers)
        self.assertIs(resolve('logging', 'root'), logging.root)
        self.assertEqual(resolve('logging', 'root.debug'), logging.root.debug)

    def test_cache_base(self):
        actual = get_cache_base()
        if os.name == 'nt' and 'LOCALAPPDATA' in os.environ:
            expected = os.path.expandvars('$localappdata')
        else:
            expected = os.path.expanduser('~')
        expected = os.path.join(expected, '.distlib')
        self.assertEqual(expected, actual)
        self.assertTrue(os.path.isdir(expected))

    @unittest.skipIf(os.name != 'posix', 'Test is only valid for POSIX')
    def test_path_to_cache_dir_posix(self):
        self.assertEqual(path_to_cache_dir('/home/user/some-file.zip'),
                        '--home--user--some-file.zip.cache')

    @unittest.skipIf(os.name != 'nt', 'Test is only valid for Windows')
    def test_path_to_cache_dir_nt(self):
        self.assertEqual(path_to_cache_dir(r'c:\Users\User\Some-File.zip'),
                        'c-----Users--User--Some-File.zip.cache')

    def test_parse_credentials(self):
        self.assertEqual(parse_credentials('example.com', ),
                         (None, None, 'example.com'))
        self.assertEqual(parse_credentials('user@example.com', ),
                         ('user', None, 'example.com'))
        self.assertEqual(parse_credentials('user:pwd@example.com', ),
                         ('user', 'pwd', 'example.com'))

    def test_ensure_slash(self):
        self.assertEqual(ensure_slash(''), '/')
        self.assertEqual(ensure_slash('/'), '/')
        self.assertEqual(ensure_slash('abc'), 'abc/')
        self.assertEqual(ensure_slash('def/'), 'def/')

    def test_split_filename(self):
        self.assertIsNone(split_filename('abl.jquery'))
        self.assertEqual(split_filename('abl.jquery-1.4.2-2'),
                         ('abl.jquery', '1.4.2-2', None))
        self.assertEqual(split_filename('python-gnupg-0.1'),
                         ('python-gnupg', '0.1', None))
        self.assertEqual(split_filename('baklabel-1.0.3-2729-py3.2'),
                         ('baklabel', '1.0.3-2729', '3.2'))
        self.assertEqual(split_filename('baklabel-1.0.3-2729-py27'),
                         ('baklabel', '1.0.3-2729', '27'))
        self.assertEqual(split_filename('advpy-0.99b'),
                         ('advpy', '0.99b', None))
        self.assertEqual(split_filename('asv_files-dev-20120501-01', 'asv_files'),
                         ('asv_files', 'dev-20120501-01', None))
        #import pdb; pdb.set_trace()
        #self.assertEqual(split_filename('asv_files-test-dev-20120501-01', 'asv_files'),
        #                 ('asv_files-test', 'dev-20120501-01', None))

    def test_events(self):
        collected = []

        def handler1(e, *args, **kwargs):
            collected.append((1, e, args, kwargs))

        def handler2(e, *args, **kwargs):
            collected.append((2, e, args, kwargs))

        def handler3(e, *args, **kwargs):
            if not args:
                raise NotImplementedError('surprise!')
            collected.append((3, e, args, kwargs))
            return (args, kwargs)

        e = EventMixin()
        e.add('A', handler1)
        self.assertRaises(ValueError, e.remove, 'B', handler1)

        cases = (
            ((1, 2), {'buckle': 'my shoe'}),
            ((3, 4), {'shut': 'the door'}),
        )

        for case in cases:
            e.publish('A', *case[0], **case[1])
            e.publish('B', *case[0], **case[1])

        for actual, source in zip(collected, cases):
            self.assertEqual(actual, (1, 'A') + source[:1] + source[1:])

        collected = []
        e.add('B', handler2)

        self.assertEqual(tuple(e.get_subscribers('A')), (handler1,))
        self.assertEqual(tuple(e.get_subscribers('B')), (handler2,))
        self.assertEqual(tuple(e.get_subscribers('C')), ())

        for case in cases:
            e.publish('A', *case[0], **case[1])
            e.publish('B', *case[0], **case[1])

        actuals = islice(collected, 0, None, 2)
        for actual, source in zip(actuals, cases):
            self.assertEqual(actual, (1, 'A') + source[:1] + source[1:])

        actuals = islice(collected, 1, None, 2)
        for actual, source in zip(actuals, cases):
            self.assertEqual(actual, (2, 'B') + source[:1] + source[1:])

        e.remove('B', handler2)

        collected = []

        for case in cases:
            e.publish('A', *case[0], **case[1])
            e.publish('B', *case[0], **case[1])

        for actual, source in zip(collected, cases):
            self.assertEqual(actual, (1, 'A') + source[:1] + source[1:])

        e.add('C', handler3)

        collected = []
        returned = []

        for case in cases:
            returned.extend(e.publish('C', *case[0], **case[1]))
            returned.extend(e.publish('C'))

        for actual, source in zip(collected, cases):
            self.assertEqual(actual, (3, 'C') + source[:1] + source[1:])

        self.assertEqual(tuple(islice(returned, 1, None, 2)), (None, None))
        actuals = islice(returned, 0, None, 2)
        for actual, expected in zip(actuals, cases):
            self.assertEqual(actual, expected)

    def test_sequencer_basic(self):
        seq = Sequencer()

        steps = (
            ('check', 'sdist'),
            ('check', 'register'),
            ('check', 'sdist'),
            ('check', 'register'),
            ('register', 'upload_sdist'),
            ('sdist', 'upload_sdist'),
            ('check', 'build_clibs'),
            ('build_clibs', 'build_ext'),
            ('build_ext', 'build_py'),
            ('build_py', 'build_scripts'),
            ('build_scripts', 'build'),
            ('build', 'test'),
            ('register', 'upload_bdist'),
            ('build', 'upload_bdist'),
            ('build', 'install_headers'),
            ('install_headers', 'install_lib'),
            ('install_lib', 'install_scripts'),
            ('install_scripts', 'install_data'),
            ('install_data', 'install_distinfo'),
            ('install_distinfo', 'install')
        )

        for pred, succ in steps:
            seq.add(pred, succ)

        # Note: these tests are sensitive to dictionary ordering
        # but work under Python 2.6, 2.7, 3.2, 3.3, 3.4
        cases = (
            ('check', ['check']),
            ('register', ['check', 'register']),
            ('sdist', ['check', 'sdist']),
            ('build_clibs', ['check', 'build_clibs']),
            ('build_ext', ['check', 'build_clibs', 'build_ext']),
            ('build_py', ['check', 'build_clibs', 'build_ext', 'build_py']),
            ('build_scripts', ['check', 'build_clibs', 'build_ext', 'build_py',
                               'build_scripts']),
            ('build', ['check', 'build_clibs', 'build_ext', 'build_py',
                       'build_scripts', 'build']),
            ('test', ['check', 'build_clibs', 'build_ext', 'build_py',
                      'build_scripts', 'build', 'test']),
            ('install_headers', ['check', 'build_clibs', 'build_ext',
                                 'build_py', 'build_scripts', 'build',
                                 'install_headers']),
            ('install_lib', ['check', 'build_clibs', 'build_ext', 'build_py',
                             'build_scripts', 'build', 'install_headers',
                             'install_lib']),
            ('install_scripts', ['check', 'build_clibs', 'build_ext',
                                 'build_py', 'build_scripts', 'build',
                                 'install_headers', 'install_lib',
                                 'install_scripts']),
            ('install_data', ['check', 'build_clibs', 'build_ext', 'build_py',
                              'build_scripts', 'build', 'install_headers',
                              'install_lib', 'install_scripts',
                              'install_data']),
            ('install_distinfo', ['check', 'build_clibs', 'build_ext',
                                  'build_py', 'build_scripts', 'build',
                                  'install_headers', 'install_lib',
                                  'install_scripts', 'install_data',
                                  'install_distinfo']),
            ('install', ['check', 'build_clibs', 'build_ext', 'build_py',
                         'build_scripts', 'build', 'install_headers',
                         'install_lib', 'install_scripts', 'install_data',
                         'install_distinfo', 'install']),
            ('upload_sdist', (['check', 'register', 'sdist', 'upload_sdist'],
                              ['check', 'sdist', 'register', 'upload_sdist'])),
            ('upload_bdist', (['check', 'build_clibs', 'build_ext', 'build_py',
                               'build_scripts', 'build', 'register',
                               'upload_bdist'],
                              ['check', 'build_clibs', 'build_ext', 'build_py',
                               'build_scripts', 'register', 'build',
                               'upload_bdist'])),
        )

        for final, expected in cases:
            actual = list(seq.get_steps(final))
            if isinstance(expected, tuple):
                self.assertIn(actual, expected)
            else:
                self.assertEqual(actual, expected)

        dot = seq.dot
        expected = '''
        digraph G {
          check -> build_clibs;
          install_lib -> install_scripts;
          register -> upload_bdist;
          build -> upload_bdist;
          build_ext -> build_py;
          install_scripts -> install_data;
          check -> sdist;
          check -> register;
          build -> install_headers;
          install_data -> install_distinfo;
          sdist -> upload_sdist;
          register -> upload_sdist;
          install_distinfo -> install;
          build -> test;
          install_headers -> install_lib;
          build_py -> build_scripts;
          build_clibs -> build_ext;
          build_scripts -> build;
        }
        '''
        expected = textwrap.dedent(expected).strip().splitlines()
        actual = dot.splitlines()
        self.assertEqual(expected[0], actual[0])
        self.assertEqual(expected[-1], actual[-1])
        self.assertEqual(set(expected[1:-1]), set(actual[1:-1]))
        actual = seq.strong_connections
        expected = [
            ('test',), ('upload_bdist',), ('install',), ('install_distinfo',),
            ('install_data',), ('install_scripts',), ('install_lib',),
            ('install_headers',), ('build',), ('build_scripts',),
            ('build_py',), ('build_ext',), ('build_clibs',), ('upload_sdist',),
            ('sdist',), ('register',), ('check',)]
        self.assertEqual(actual, expected)

    def test_sequencer_cycle(self):
        seq = Sequencer()
        seq.add('A', 'B')
        seq.add('B', 'C')
        seq.add('C', 'D')
        self.assertEqual(list(seq.get_steps('D')), ['A', 'B', 'C', 'D'])
        seq.add('C', 'A')
        self.assertEqual(list(seq.get_steps('D')), ['C', 'A', 'B', 'D'])
        self.assertFalse(seq.is_step('E'))
        self.assertRaises(ValueError, seq.get_steps, 'E')
        seq.add_node('E')
        self.assertTrue(seq.is_step('E'))
        self.assertEqual(list(seq.get_steps('E')), ['E'])
        seq.remove_node('E')
        self.assertFalse(seq.is_step('E'))
        self.assertRaises(ValueError, seq.get_steps, 'E')
        seq.remove('C', 'A')
        self.assertEqual(list(seq.get_steps('D')), ['A', 'B', 'C', 'D'])

    def test_unarchive(self):
        import zipfile, tarfile

        good_archives = (
            ('good.zip', zipfile.ZipFile, 'r', 'namelist'),
            ('good.tar', tarfile.open, 'r', 'getnames'),
            ('good.tar.gz', tarfile.open, 'r:gz', 'getnames'),
            ('good.tar.bz2', tarfile.open, 'r:bz2', 'getnames'),
        )
        bad_archives = ('bad.zip', 'bad.tar', 'bad.tar.gz', 'bad.tar.bz2')

        for name, cls, mode, lister in good_archives:
            td = tempfile.mkdtemp()
            try:
                name = os.path.join(HERE, name)
                unarchive(name, td)
                archive = cls(name, mode)
                names = getattr(archive, lister)()
                for name in names:
                    p = os.path.join(td, name)
                    self.assertTrue(os.path.exists(p))
            finally:
                shutil.rmtree(td)

        for name in bad_archives:
            name = os.path.join(HERE, name)
            td = tempfile.mkdtemp()
            try:
                self.assertRaises(ValueError, unarchive, name, td)
            finally:
                shutil.rmtree(td)

    def test_string_sequence(self):
        self.assertTrue(is_string_sequence(['a']))
        self.assertTrue(is_string_sequence(['a', 'b']))
        self.assertFalse(is_string_sequence(['a', 'b', None]))
        self.assertRaises(AssertionError, is_string_sequence, [])

    def test_package_data(self):
        data = get_package_data('config', '0.3.6')
        self.assertTrue(data)
        self.assertTrue('metadata' in data)
        metadata = data['metadata']
        self.assertEqual(metadata['name'], 'config')
        self.assertEqual(metadata['version'], '0.3.6')
        data = get_package_data('config', '0.3.5')
        self.assertFalse(data)

class ProgressTestCase(unittest.TestCase):
    def test_basic(self):
        if os.name == 'nt':
            speed1 = '20 KB/s'
            speed2 = '22 KB/s'
        else:
            speed1 = '19 KB/s'
            speed2 = '22 KB/s'
        expected = (
            (' 10 %', 'ETA : 00:00:04', speed1),
            (' 20 %', 'ETA : 00:00:04', speed1),
            (' 30 %', 'ETA : 00:00:03', speed1),
            (' 40 %', 'ETA : 00:00:03', speed1),
            (' 50 %', 'ETA : 00:00:02', speed1),
            (' 60 %', 'ETA : 00:00:02', speed1),
            (' 70 %', 'ETA : 00:00:01', speed1),
            (' 80 %', 'ETA : 00:00:01', speed1),
            (' 90 %', 'ETA : 00:00:00', speed1),
            ('100 %', 'Done: 00:00:04', speed2),
        )
        bar = Progress(maxval=100000).start()
        for i, v in enumerate(range(10000, 100000, 10000)):
            time.sleep(0.5)
            bar.update(v)
            p, e, s = expected[i]
            self.assertEqual(bar.percentage, p)
            self.assertEqual(bar.ETA, e)
            self.assertEqual(bar.speed, s)
        bar.stop()
        p, e, s = expected[i + 1]
        self.assertEqual(bar.percentage, p)
        self.assertEqual(bar.ETA, e)
        self.assertEqual(bar.speed, s)

    def test_unknown(self):
        if os.name == 'nt':
            speed = '20 KB/s'
        else:
            speed = '19 KB/s'
        expected = (
            (' ?? %', 'ETA : ??:??:??', speed),
            (' ?? %', 'ETA : ??:??:??', speed),
            (' ?? %', 'ETA : ??:??:??', speed),
            (' ?? %', 'ETA : ??:??:??', speed),
            (' ?? %', 'ETA : ??:??:??', speed),
            (' ?? %', 'ETA : ??:??:??', speed),
            (' ?? %', 'ETA : ??:??:??', speed),
            (' ?? %', 'ETA : ??:??:??', speed),
            (' ?? %', 'ETA : ??:??:??', speed),
            ('100 %', 'Done: 00:00:04', speed),
        )
        bar = Progress(maxval=None).start()
        for i, v in enumerate(range(10000, 100000, 10000)):
            time.sleep(0.5)
            bar.update(v)
            p, e, s = expected[i]
            self.assertEqual(bar.percentage, p)
            self.assertEqual(bar.ETA, e)
            self.assertEqual(bar.speed, s)
        bar.stop()
        p, e, s = expected[i + 1]
        self.assertEqual(bar.percentage, p)
        self.assertEqual(bar.ETA, e)
        self.assertEqual(bar.speed, s)

class FileOpsTestCase(unittest.TestCase):

    def setUp(self):
        self.fileop = FileOperator()
        self.workdir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.isdir(self.workdir):
            shutil.rmtree(self.workdir)

    def test_ensure_dir(self):
        td = self.workdir
        os.rmdir(td)
        self.fileop.ensure_dir(td)
        self.assertTrue(os.path.exists(td))
        self.fileop.dry_run = True
        os.rmdir(td)
        self.fileop.ensure_dir(td)
        self.assertFalse(os.path.exists(td))

    def test_ensure_removed(self):
        td = self.workdir
        self.assertTrue(os.path.exists(td))
        self.fileop.dry_run = True
        self.fileop.ensure_removed(td)
        self.assertTrue(os.path.exists(td))
        self.fileop.dry_run = False
        self.fileop.ensure_removed(td)
        self.assertFalse(os.path.exists(td))

    def test_is_writable(self):
        sd = 'subdir'
        ssd = 'subsubdir'
        path = os.path.join(self.workdir, sd, ssd)
        os.makedirs(path)
        path = os.path.join(path, 'test')
        self.assertTrue(self.fileop.is_writable(path))
        if os.name == 'posix':
            self.assertFalse(self.fileop.is_writable('/etc'))

    def test_byte_compile(self):
        path = os.path.join(self.workdir, 'hello.py')
        dpath = cache_from_source(path, True)
        self.fileop.write_text_file(path, 'print("Hello, world!")', 'utf-8')
        self.fileop.byte_compile(path, optimize=False)
        self.assertTrue(os.path.exists(dpath))

    def write_some_files(self):
        path = os.path.join(self.workdir, 'file1')
        written = []
        self.fileop.write_text_file(path, 'test', 'utf-8')
        written.append(path)
        path = os.path.join(self.workdir, 'file2')
        self.fileop.copy_file(written[0], path)
        written.append(path)
        path = os.path.join(self.workdir, 'dir1')
        self.fileop.ensure_dir(path)
        return set(written), set([path])

    def test_commit(self):
        # will assert if record isn't set
        self.assertRaises(AssertionError, self.fileop.commit)
        self.fileop.record = True
        expected = self.write_some_files()
        actual = self.fileop.commit()
        self.assertEqual(actual, expected)
        self.assertFalse(self.fileop.record)

    def test_rollback(self):
        # will assert if record isn't set
        self.assertRaises(AssertionError, self.fileop.commit)
        self.fileop.record = True
        expected = self.write_some_files()
        actual = self.fileop.rollback()
        self.assertEqual(os.listdir(self.workdir), [])
        self.assertFalse(self.fileop.record)
