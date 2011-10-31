"""
TODO doc me

"""


import csv
import os
import zlib
import cPickle as pickle
import sqlite3


__all__ = ['fromcsv', 'frompickle', 'fromsqlite3', 'tocsv', 'topickle', \
           'tosqlite3', 'crc32sum', 'adler32sum', 'statsum', 'fromdb']


class Uncacheable(Exception):
    pass # TODO


def crc32sum(filename):
    """
    Compute the CRC32 checksum of the file at the given location. Returns
    the checksum as an integer, use hex(result) to view as hexadecimal.
    
    """
    
    checksum = None
    with open(filename, 'rb') as f:
        while True:
            data = f.read(8192)
            if not data:
                break
            if checksum is None:
                checksum = zlib.crc32(data) & 0xffffffffL # deal with signed integer
            else:
                checksum = zlib.crc32(data, checksum) & 0xffffffffL # deal with signed integer
    return checksum


def adler32sum(filename):
    """
    Compute the Adler 32 checksum of the file at the given location. Returns
    the checksum as an integer, use hex(result) to view as hexadecimal.
    
    """
    
    checksum = None
    with open(filename, 'rb') as f:
        while True:
            data = f.read(8192)
            if not data:
                break
            if checksum is None:
                checksum = zlib.adler32(data) & 0xffffffffL # deal with signed integer
            else:
                checksum = zlib.adler32(data, checksum) & 0xffffffffL # deal with signed integer
    return checksum


def statsum(filename):
    """
    Compute a crude checksum of the file by hashing the file's absolute path
    name, the file size, and the file's time of last modification. N.B., on
    some systems this will give a 1s resolution, i.e., any changes to a file
    within the same second that preserve the file size will *not* change the
    result.
    
    """
    
    return hash((os.path.abspath(filename), 
                 os.path.getsize(filename), 
                 os.path.getmtime(filename)))
        

def fromcsv(filename, checksumfun=statsum, **kwargs):
    """
    Wrapper for the standard `csv.reader` function. Returns a table providing
    access to the data in the given delimited file. The `filename` argument is the
    path of the delimited file, all other keyword arguments are passed to 
    `csv.reader`. E.g.::

        >>> import csv
        >>> import tempfile
        >>> # set up a temporary CSV file to demonstrate with
        ... f = tempfile.NamedTemporaryFile(delete=False)
        >>> writer = csv.writer(f, delimiter='\\t')
        >>> writer.writerow(['foo', 'bar'])
        >>> writer.writerow(['a', 1])
        >>> writer.writerow(['b', 2])
        >>> writer.writerow(['c', 2])
        >>> f.close()
        >>> # now demonstrate the use of petl.fromcsv
        ... from petl import fromcsv, look
        >>> table = fromcsv(f.name, delimiter='\\t')
        >>> look(table)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'a'   | '1'   |
        +-------+-------+
        | 'b'   | '2'   |
        +-------+-------+
        | 'c'   | '2'   |
        +-------+-------+

    Note that all data values are strings, and any intended numeric values will
    need to be converted, see also `petl.convert`.
    
    The returned table object implements the `cachetag` method, which by default
    uses the `statsum` function to generate a checksum of the underlying file.
    Note that `statsum` is cheap to compute but crude as it relies on file size 
    and time of modification, and on some systems this will not reveal changes 
    within the same second that preserve file size. If you need a finer level
    of granularity, use either `adler32sum` or `crc32sum` instead.
    
    """

    return CSVView(filename, checksumfun=checksumfun, **kwargs)


class CSVView(object):
    
    def __init__(self, filename, checksumfun=statsum, **kwargs):
        self.filename = filename
        self.checksumfun = checksumfun
        self.kwargs = kwargs
        
    def __iter__(self):
        with open(self.filename, 'rb') as file:
            reader = csv.reader(file, **self.kwargs)
            for row in reader:
                yield row
                
    def cachetag(self):
        p = self.filename
        if os.path.isfile(p):
            checksum = self.checksumfun(p)
            return hash((checksum, tuple(self.kwargs.items()))) 
        else:
            raise Uncacheable
                
    
def frompickle(filename, checksumfun=statsum):
    """
    Returns a table providing access to the data pickled in the given file. The 
    rows in the table should have been pickled to the file one at a time. E.g.::

        >>> import pickle
        >>> import tempfile
        >>> # set up a temporary file to demonstrate with
        ... f = tempfile.NamedTemporaryFile(delete=False)
        >>> pickle.dump(['foo', 'bar'], f)
        >>> pickle.dump(['a', 1], f)
        >>> pickle.dump(['b', 2], f)
        >>> pickle.dump(['c', 2.5], f)
        >>> f.close()
        >>> # now demonstrate the use of petl.frompickle
        ... from petl import frompickle, look
        >>> table = frompickle(f.name)
        >>> look(table)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'a'   | 1     |
        +-------+-------+
        | 'b'   | 2     |
        +-------+-------+
        | 'c'   | 2.5   |
        +-------+-------+

    The returned table object implements the `cachetag` method, which by default
    uses the `statsum` function to generate a checksum of the underlying file.
    Note that `statsum` is cheap to compute but crude as it relies on file size 
    and time of modification, and on some systems this will not reveal changes 
    within the same second that preserve file size. If you need a finer level
    of granularity, use either `adler32sum` or `crc32sum` instead.
    
    """
    
    return PickleView(filename, checksumfun=checksumfun)
    
    
class PickleView(object):

    def __init__(self, filename, checksumfun=statsum):
        self.filename = filename
        self.checksumfun = checksumfun
        
    def __iter__(self):
        with open(self.filename, 'rb') as file:
            try:
                while True:
                    yield pickle.load(file)
            except EOFError:
                pass
                
    def cachetag(self):
        p = self.filename
        if os.path.isfile(p):
            return self.checksumfun(p)
        else:
            raise Uncacheable
    

def fromsqlite3(filename, query, checksumfun=statsum):
    """
    Provides access to data from an sqlite3 connection via a given query. E.g.::

        >>> import sqlite3
        >>> from petl import look, fromsqlite3    
        >>> # initial data
        >>> data = [['a', 1],
        ...         ['b', 2],
        ...         ['c', 2.0]]
        >>> connection = sqlite3.connect('tmp.db')
        >>> c = connection.cursor()
        >>> c.execute('create table foobar (foo, bar)')
        <sqlite3.Cursor object at 0x2240b90>
        >>> for row in data:
        ...     c.execute('insert into foobar values (?, ?)', row)
        ... 
        <sqlite3.Cursor object at 0x2240b90>
        <sqlite3.Cursor object at 0x2240b90>
        <sqlite3.Cursor object at 0x2240b90>
        >>> connection.commit()
        >>> c.close()
        >>> # demonstrate the petl.fromsqlite3 function
        ... table = fromsqlite3('tmp.db', 'select * from foobar')
        >>> look(table)    
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | u'a'  | 1     |
        +-------+-------+
        | u'b'  | 2     |
        +-------+-------+
        | u'c'  | 2.0   |
        +-------+-------+

    The returned table object implements the `cachetag` method, which by default
    uses the `statsum` function to generate a checksum of the underlying file.
    Note that `statsum` is cheap to compute but crude as it relies on file size 
    and time of modification, and on some systems this will not reveal changes 
    within the same second that preserve file size. If you need a finer level
    of granularity, use either `adler32sum` or `crc32sum` instead.
    
    """
    
    return Sqlite3View(filename, query, checksumfun)


class Sqlite3View(object):

    def __init__(self, filename, query, checksumfun=statsum):
        self.filename = filename
        self.query = query
        self.checksumfun = checksumfun
        
    def __iter__(self):
        connection = sqlite3.connect(self.filename)
        cursor = connection.execute(self.query)
        fields = [d[0] for d in cursor.description]
        yield fields
        for result in cursor:
            yield result
        connection.close()

    def cachetag(self):
        p = self.filename
        if os.path.isfile(p):
            checksum = self.checksumfun(p)
            return hash((checksum, self.query))
        else:
            raise Uncacheable
                
    
def fromdb(connection, query):
    """
    Provides access to data from any DB-API 2.0 connection via a given query. 
    E.g., using `sqlite3`::

        >>> import sqlite3
        >>> from petl import look, fromdb
        >>> connection = sqlite3.connect('test.db')
        >>> table = fromdb(connection, 'select * from foobar')
        >>> look(table)
        
    E.g., using `psycopg2` (assuming you've installed it first)::
    
        >>> import psycopg2
        >>> from petl import look, fromdb
        >>> connection = psycopg2.connect("dbname=test user=postgres")
        >>> table = fromdb(connection, 'select * from test')
        >>> look(table)
        
    E.g., using `MySQLdb` (assuming you've installed it first)::
    
        >>> import MySQLdb
        >>> from petl import look, fromdb
        >>> connection = MySQLdb.connect(passwd="moonpie", db="thangs")
        >>> table = fromdb(connection, 'select * from test')
        >>> look(table)
        
    The returned table object does not implement the `cachetag` method.
        
    """
    
    return DbView(connection, query)


class DbView(object):

    def __init__(self, connection, query):
        self.connection = connection
        self.query = query
        
    def __iter__(self):
        cursor = self.connection.execute(self.query)
        fields = [d[0] for d in cursor.description]
        yield fields
        for result in cursor:
            yield result

    
def tocsv(table, filename, *args, **kwargs):
    """
    TODO doc me
    
    """
    

def topickle(table, filename):
    """
    TODO doc me
    
    """
    

def tosqlite3(table):
    """
    TODO doc me
    
    """
    
    