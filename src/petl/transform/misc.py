"""
Functions for transforming tables.

"""

from itertools import islice, groupby, product, chain, izip_longest, izip
from collections import deque, defaultdict
from operator import itemgetter
import re


from petl.util import asindices, rowgetter, \
    expr, valueset, header, data, limits, itervalues, \
    values, hybridrows, rowgroupby, \
    OrderedDict, RowContainer, SortableItem, \
    sortable_itemgetter, count

from petl.transform.sorts import sort

from petl.transform.selects import selecteq, selectrangeopenleft, \
    selectrangeopen


import logging
logger = logging.getLogger(__name__)
warning = logger.warning
info = logger.info
debug = logger.debug


def cut(table, *args, **kwargs):
    """
    Choose and/or re-order columns. E.g.::

        >>> from petl import look, cut    
        >>> look(table1)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'A'   | 1     | 2.7   |
        +-------+-------+-------+
        | 'B'   | 2     | 3.4   |
        +-------+-------+-------+
        | 'B'   | 3     | 7.8   |
        +-------+-------+-------+
        | 'D'   | 42    | 9.0   |
        +-------+-------+-------+
        | 'E'   | 12    |       |
        +-------+-------+-------+
        
        >>> table2 = cut(table1, 'foo', 'baz')
        >>> look(table2)
        +-------+-------+
        | 'foo' | 'baz' |
        +=======+=======+
        | 'A'   | 2.7   |
        +-------+-------+
        | 'B'   | 3.4   |
        +-------+-------+
        | 'B'   | 7.8   |
        +-------+-------+
        | 'D'   | 9.0   |
        +-------+-------+
        | 'E'   | None  |
        +-------+-------+
        
        >>> # fields can also be specified by index, starting from zero
        ... table3 = cut(table1, 0, 2)
        >>> look(table3)
        +-------+-------+
        | 'foo' | 'baz' |
        +=======+=======+
        | 'A'   | 2.7   |
        +-------+-------+
        | 'B'   | 3.4   |
        +-------+-------+
        | 'B'   | 7.8   |
        +-------+-------+
        | 'D'   | 9.0   |
        +-------+-------+
        | 'E'   | None  |
        +-------+-------+
        
        >>> # field names and indices can be mixed
        ... table4 = cut(table1, 'bar', 0)
        >>> look(table4)
        +-------+-------+
        | 'bar' | 'foo' |
        +=======+=======+
        | 1     | 'A'   |
        +-------+-------+
        | 2     | 'B'   |
        +-------+-------+
        | 3     | 'B'   |
        +-------+-------+
        | 42    | 'D'   |
        +-------+-------+
        | 12    | 'E'   |
        +-------+-------+
        
        >>> # select a range of fields
        ... table5 = cut(table1, *range(0, 2))
        >>> look(table5)    
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'A'   | 1     |
        +-------+-------+
        | 'B'   | 2     |
        +-------+-------+
        | 'B'   | 3     |
        +-------+-------+
        | 'D'   | 42    |
        +-------+-------+
        | 'E'   | 12    |
        +-------+-------+

    Note that any short rows will be padded with `None` values (or whatever is
    provided via the `missing` keyword argument).
    
    See also :func:`cutout`.
    
    """

    # support passing a single list or tuple of fields
    if len(args) == 1 and isinstance(args[0], (list, tuple)):
        args = args[0]
            
    return CutView(table, args, **kwargs)


class CutView(RowContainer):
    
    def __init__(self, source, spec, missing=None):
        self.source = source
        self.spec = spec
        self.missing = missing
        
    def __iter__(self):
        return itercut(self.source, self.spec, self.missing)
    
        
def itercut(source, spec, missing=None):
    it = iter(source)
    spec = tuple(spec)  # make sure no-one can change midstream
    
    # convert field selection into field indices
    flds = it.next()
    indices = asindices(flds, spec)

    # define a function to transform each row in the source data 
    # according to the field selection
    transform = rowgetter(*indices)
    
    # yield the transformed field names
    yield transform(flds)
    
    # construct the transformed data
    for row in it:
        try:
            yield transform(row) 
        except IndexError:
            # row is short, let's be kind and fill in any missing fields
            yield tuple(row[i] if i < len(row) else missing for i in indices)

    
def cutout(table, *args, **kwargs):
    """
    Remove fields. E.g.::

        >>> from petl import cutout, look
        >>> look(table1)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'A'   | 1     | 2.7   |
        +-------+-------+-------+
        | 'B'   | 2     | 3.4   |
        +-------+-------+-------+
        | 'B'   | 3     | 7.8   |
        +-------+-------+-------+
        | 'D'   | 42    | 9.0   |
        +-------+-------+-------+
        | 'E'   | 12    |       |
        +-------+-------+-------+
        
        >>> table2 = cutout(table1, 'bar')
        >>> look(table2)
        +-------+-------+
        | 'foo' | 'baz' |
        +=======+=======+
        | 'A'   | 2.7   |
        +-------+-------+
        | 'B'   | 3.4   |
        +-------+-------+
        | 'B'   | 7.8   |
        +-------+-------+
        | 'D'   | 9.0   |
        +-------+-------+
        | 'E'   | None  |
        +-------+-------+
        
    See also :func:`cut`.
    
    .. versionadded:: 0.3
    
    """

    return CutOutView(table, args, **kwargs)


class CutOutView(RowContainer):
    
    def __init__(self, source, spec, missing=None):
        self.source = source
        self.spec = spec
        self.missing = missing
        
    def __iter__(self):
        return itercutout(self.source, self.spec, self.missing)
    
        
def itercutout(source, spec, missing=None):
    it = iter(source)
    spec = tuple(spec) # make sure no-one can change midstream
    
    # convert field selection into field indices
    flds = it.next()
    indicesout = asindices(flds, spec)
    indices = [i for i in range(len(flds)) if i not in indicesout]
    
    # define a function to transform each row in the source data 
    # according to the field selection
    transform = rowgetter(*indices)
    
    # yield the transformed field names
    yield transform(flds)
    
    # construct the transformed data
    for row in it:
        try:
            yield transform(row) 
        except IndexError:
            # row is short, let's be kind and fill in any missing fields
            yield tuple(row[i] if i < len(row) else missing for i in indices)

    
def cat(*tables, **kwargs):
    """
    Concatenate data from two or more tables. E.g.::
    
        >>> from petl import look, cat
        >>> look(table1)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 1     | 'A'   |
        +-------+-------+
        | 2     | 'B'   |
        +-------+-------+
        
        >>> look(table2)
        +-------+-------+
        | 'bar' | 'baz' |
        +=======+=======+
        | 'C'   | True  |
        +-------+-------+
        | 'D'   | False |
        +-------+-------+
        
        >>> table3 = cat(table1, table2)
        >>> look(table3)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 1     | 'A'   | None  |
        +-------+-------+-------+
        | 2     | 'B'   | None  |
        +-------+-------+-------+
        | None  | 'C'   | True  |
        +-------+-------+-------+
        | None  | 'D'   | False |
        +-------+-------+-------+
        
        >>> # can also be used to square up a single table with uneven rows
        ... look(table4)
        +-------+-------+--------+------+
        | 'foo' | 'bar' | 'baz'  |      |
        +=======+=======+========+======+
        | 'A'   | 1     | 2      |      |
        +-------+-------+--------+------+
        | 'B'   | '2'   | '3.4'  |      |
        +-------+-------+--------+------+
        | u'B'  | u'3'  | u'7.8' | True |
        +-------+-------+--------+------+
        | 'D'   | 'xyz' | 9.0    |      |
        +-------+-------+--------+------+
        | 'E'   | None  |        |      |
        +-------+-------+--------+------+
        
        >>> look(cat(table4))
        +-------+-------+--------+
        | 'foo' | 'bar' | 'baz'  |
        +=======+=======+========+
        | 'A'   | 1     | 2      |
        +-------+-------+--------+
        | 'B'   | '2'   | '3.4'  |
        +-------+-------+--------+
        | u'B'  | u'3'  | u'7.8' |
        +-------+-------+--------+
        | 'D'   | 'xyz' | 9.0    |
        +-------+-------+--------+
        | 'E'   | None  | None   |
        +-------+-------+--------+
        
        >>> # use the header keyword argument to specify a fixed set of fields 
        ... look(table5)
        +-------+-------+
        | 'bar' | 'foo' |
        +=======+=======+
        | 'A'   | 1     |
        +-------+-------+
        | 'B'   | 2     |
        +-------+-------+
        
        >>> table6 = cat(table5, header=['A', 'foo', 'B', 'bar', 'C'])
        >>> look(table6)
        +------+-------+------+-------+------+
        | 'A'  | 'foo' | 'B'  | 'bar' | 'C'  |
        +======+=======+======+=======+======+
        | None | 1     | None | 'A'   | None |
        +------+-------+------+-------+------+
        | None | 2     | None | 'B'   | None |
        +------+-------+------+-------+------+
        
        >>> # using the header keyword argument with two input tables
        ... look(table7)
        +-------+-------+
        | 'bar' | 'foo' |
        +=======+=======+
        | 'A'   | 1     |
        +-------+-------+
        | 'B'   | 2     |
        +-------+-------+
        
        >>> look(table8)
        +-------+-------+
        | 'bar' | 'baz' |
        +=======+=======+
        | 'C'   | True  |
        +-------+-------+
        | 'D'   | False |
        +-------+-------+
        
        >>> table9 = cat(table7, table8, header=['A', 'foo', 'B', 'bar', 'C'])
        >>> look(table9)
        +------+-------+------+-------+------+
        | 'A'  | 'foo' | 'B'  | 'bar' | 'C'  |
        +======+=======+======+=======+======+
        | None | 1     | None | 'A'   | None |
        +------+-------+------+-------+------+
        | None | 2     | None | 'B'   | None |
        +------+-------+------+-------+------+
        | None | None  | None | 'C'   | None |
        +------+-------+------+-------+------+
        | None | None  | None | 'D'   | None |
        +------+-------+------+-------+------+    
    
    Note that the tables do not need to share exactly the same fields, any 
    missing fields will be padded with `None` or whatever is provided via the 
    `missing` keyword argument. 

    .. versionchanged:: 0.5
    
    By default, the fields for the output table will be determined as the 
    union of all fields found in the input tables. Use the `header` keyword 
    argument to override this behaviour and specify a fixed set of fields for 
    the output table. 
    
    """
    
    return CatView(tables, **kwargs)
    
    
class CatView(RowContainer):
    
    def __init__(self, sources, missing=None, header=None):
        self.sources = sources
        self.missing = missing
        if header is not None:
            header = tuple(header) # ensure hashable
        self.header = header

    def __iter__(self):
        return itercat(self.sources, self.missing, self.header)
    

def itercat(sources, missing, header):
    its = [iter(t) for t in sources]
    source_flds_lists = [it.next() for it in its]

    if header is None:
        # determine output fields by gathering all fields found in the sources
        outflds = list()
        for flds in source_flds_lists:
            for f in flds:
                if f not in outflds:
                    # add any new fields as we find them
                    outflds.append(f)
    else:
        # predetermined output fields
        outflds = header
    yield tuple(outflds)

    # output data rows
    for source_index, it in enumerate(its):

        flds = source_flds_lists[source_index]
        
        # now construct and yield the data rows
        for row in it:
            try:
                # should be quickest to do this way
                yield tuple(row[flds.index(f)] if f in flds else missing for f in outflds)
            except IndexError:
                # handle short rows
                outrow = [missing] * len(outflds)
                for i, f in enumerate(flds):
                    try:
                        outrow[outflds.index(f)] = row[i]
                    except IndexError:
                        pass # be relaxed about short rows
                yield tuple(outrow)


def addfield(table, field, value=None, index=None):
    """
    Add a field with a fixed or calculated value. E.g.::
    
        >>> from petl import addfield, look
        >>> look(table1)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'M'   | 12    |
        +-------+-------+
        | 'F'   | 34    |
        +-------+-------+
        | '-'   | 56    |
        +-------+-------+
        
        >>> # using a fixed value
        ... table2 = addfield(table1, 'baz', 42)
        >>> look(table2)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'M'   | 12    | 42    |
        +-------+-------+-------+
        | 'F'   | 34    | 42    |
        +-------+-------+-------+
        | '-'   | 56    | 42    |
        +-------+-------+-------+
        
        >>> # calculating the value
        ... table2 = addfield(table1, 'baz', lambda rec: rec['bar'] * 2)
        >>> look(table2)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'M'   | 12    | 24    |
        +-------+-------+-------+
        | 'F'   | 34    | 68    |
        +-------+-------+-------+
        | '-'   | 56    | 112   |
        +-------+-------+-------+
        
        >>> # an expression string can also be used via expr
        ... from petl import expr
        >>> table3 = addfield(table1, 'baz', expr('{bar} * 2'))
        >>> look(table3)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'M'   | 12    | 24    |
        +-------+-------+-------+
        | 'F'   | 34    | 68    |
        +-------+-------+-------+
        | '-'   | 56    | 112   |
        +-------+-------+-------+
        
    .. versionchanged:: 0.10
    
    Renamed 'extend' to 'addfield'.
    
    """

    return AddFieldView(table, field, value=value, index=index)


class AddFieldView(RowContainer):
    
    def __init__(self, source, field, value=None, index=None):
        self.source = source
        self.field = field
        self.value = value
        self.index = index
        
    def __iter__(self):
        return iteraddfield(self.source, self.field, self.value, self.index)
    

def iteraddfield(source, field, value, index):
    it = iter(source)
    flds = it.next()
    
    # determine index of new field
    if index is None:
        index = len(flds)
        
    # construct output fields
    outflds = list(flds)    
    outflds.insert(index, field)
    yield tuple(outflds)

    # hybridise rows if using calculated value
    if callable(value):
        for row in hybridrows(flds, it):
            outrow = list(row)
            v = value(row)
            outrow.insert(index, v)
            yield tuple(outrow)
    else:
        for row in it:
            outrow = list(row)
            outrow.insert(index, value)
            yield tuple(outrow)
        
    
def rowslice(table, *sliceargs):
    """
    Choose a subsequence of data rows. E.g.::
    
        >>> from petl import rowslice, look
        >>> look(table1)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'a'   | 1     |
        +-------+-------+
        | 'b'   | 2     |
        +-------+-------+
        | 'c'   | 5     |
        +-------+-------+
        | 'd'   | 7     |
        +-------+-------+
        | 'f'   | 42    |
        +-------+-------+
        
        >>> table2 = rowslice(table1, 2)
        >>> look(table2)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'a'   | 1     |
        +-------+-------+
        | 'b'   | 2     |
        +-------+-------+
        
        >>> table3 = rowslice(table1, 1, 4)
        >>> look(table3)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'b'   | 2     |
        +-------+-------+
        | 'c'   | 5     |
        +-------+-------+
        | 'd'   | 7     |
        +-------+-------+
        
        >>> table4 = rowslice(table1, 0, 5, 2)
        >>> look(table4)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'a'   | 1     |
        +-------+-------+
        | 'c'   | 5     |
        +-------+-------+
        | 'f'   | 42    |
        +-------+-------+
        
    .. versionchanged:: 0.3
    
    Positional arguments can be used to slice the data rows. The `sliceargs` are 
    passed to :func:`itertools.islice`.

    """

    return RowSliceView(table, *sliceargs)


class RowSliceView(RowContainer):
    
    def __init__(self, source, *sliceargs):
        self.source = source
        if not sliceargs:
            self.sliceargs = (None,)
        else:
            self.sliceargs = sliceargs
        
    def __iter__(self):
        return iterrowslice(self.source, self.sliceargs)


def iterrowslice(source, sliceargs):    
    it = iter(source)
    yield tuple(it.next()) # fields
    for row in islice(it, *sliceargs):
        yield tuple(row)


def head(table, n=5):
    """
    Choose the first n data rows. E.g.::

        >>> from petl import head, look
        >>> look(table1)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'a'   | 1     |
        +-------+-------+
        | 'b'   | 2     |
        +-------+-------+
        | 'c'   | 5     |
        +-------+-------+
        | 'd'   | 7     |
        +-------+-------+
        | 'f'   | 42    |
        +-------+-------+
        | 'f'   | 3     |
        +-------+-------+
        | 'h'   | 90    |
        +-------+-------+
        
        >>> table2 = head(table1, 4)
        >>> look(table2)    
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'a'   | 1     |
        +-------+-------+
        | 'b'   | 2     |
        +-------+-------+
        | 'c'   | 5     |
        +-------+-------+
        | 'd'   | 7     |
        +-------+-------+

    Syntactic sugar, equivalent to ``rowslice(table, n)``.
    
    """

    return rowslice(table, n)

        
def tail(table, n=5):
    """
    Choose the last n data rows. 
    
    E.g.::

        >>> from petl import tail, look
        >>> look(table1)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'a'   | 1     |
        +-------+-------+
        | 'b'   | 2     |
        +-------+-------+
        | 'c'   | 5     |
        +-------+-------+
        | 'd'   | 7     |
        +-------+-------+
        | 'f'   | 42    |
        +-------+-------+
        | 'f'   | 3     |
        +-------+-------+
        | 'h'   | 90    |
        +-------+-------+
        | 'k'   | 12    |
        +-------+-------+
        | 'l'   | 77    |
        +-------+-------+
        | 'q'   | 2     |
        +-------+-------+
        
        >>> table2 = tail(table1, 4)
        >>> look(table2)    
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'h'   | 90    |
        +-------+-------+
        | 'k'   | 12    |
        +-------+-------+
        | 'l'   | 77    |
        +-------+-------+
        | 'q'   | 2     |
        +-------+-------+
        
    See also :func:`head`, :func:`rowslice`.

    """

    return TailView(table, n)


class TailView(RowContainer):
    
    def __init__(self, source, n):
        self.source = source
        self.n = n
        
    def __iter__(self):
        return itertail(self.source, self.n)


def itertail(source, n):
    it = iter(source)
    yield tuple(it.next()) # fields
    cache = deque()
    for row in it:
        cache.append(row)
        if len(cache) > n:
            cache.popleft()
    for row in cache:
        yield tuple(row)

def melt(table, key=None, variables=None, variablefield='variable', valuefield='value'):
    """
    Reshape a table, melting fields into data. E.g.::

        >>> from petl import melt, look
        >>> look(table1)
        +------+----------+-------+
        | 'id' | 'gender' | 'age' |
        +======+==========+=======+
        | 1    | 'F'      | 12    |
        +------+----------+-------+
        | 2    | 'M'      | 17    |
        +------+----------+-------+
        | 3    | 'M'      | 16    |
        +------+----------+-------+
        
        >>> table2 = melt(table1, 'id')
        >>> look(table2)
        +------+------------+---------+
        | 'id' | 'variable' | 'value' |
        +======+============+=========+
        | 1    | 'gender'   | 'F'     |
        +------+------------+---------+
        | 1    | 'age'      | 12      |
        +------+------------+---------+
        | 2    | 'gender'   | 'M'     |
        +------+------------+---------+
        | 2    | 'age'      | 17      |
        +------+------------+---------+
        | 3    | 'gender'   | 'M'     |
        +------+------------+---------+
        | 3    | 'age'      | 16      |
        +------+------------+---------+
        
        >>> # compound keys are supported
        ... look(table3)
        +------+--------+----------+----------+
        | 'id' | 'time' | 'height' | 'weight' |
        +======+========+==========+==========+
        | 1    | 11     | 66.4     | 12.2     |
        +------+--------+----------+----------+
        | 2    | 16     | 53.2     | 17.3     |
        +------+--------+----------+----------+
        | 3    | 12     | 34.5     | 9.4      |
        +------+--------+----------+----------+
        
        >>> table4 = melt(table3, key=['id', 'time'])
        >>> look(table4)
        +------+--------+------------+---------+
        | 'id' | 'time' | 'variable' | 'value' |
        +======+========+============+=========+
        | 1    | 11     | 'height'   | 66.4    |
        +------+--------+------------+---------+
        | 1    | 11     | 'weight'   | 12.2    |
        +------+--------+------------+---------+
        | 2    | 16     | 'height'   | 53.2    |
        +------+--------+------------+---------+
        | 2    | 16     | 'weight'   | 17.3    |
        +------+--------+------------+---------+
        | 3    | 12     | 'height'   | 34.5    |
        +------+--------+------------+---------+
        | 3    | 12     | 'weight'   | 9.4     |
        +------+--------+------------+---------+
        
        >>> # a subset of variable fields can be selected
        ... table5 = melt(table3, key=['id', 'time'], variables=['height'])    
        >>> look(table5)
        +------+--------+------------+---------+
        | 'id' | 'time' | 'variable' | 'value' |
        +======+========+============+=========+
        | 1    | 11     | 'height'   | 66.4    |
        +------+--------+------------+---------+
        | 2    | 16     | 'height'   | 53.2    |
        +------+--------+------------+---------+
        | 3    | 12     | 'height'   | 34.5    |
        +------+--------+------------+---------+

    See also :func:`recast`.
    
    """
    
    return MeltView(table, key=key, variables=variables, 
                    variablefield=variablefield, 
                    valuefield=valuefield)
    
    
class MeltView(RowContainer):
    
    def __init__(self, source, key=None, variables=None, 
                 variablefield='variable', valuefield='value'):
        self.source = source
        self.key = key
        self.variables = variables
        self.variablefield = variablefield
        self.valuefield = valuefield
        
    def __iter__(self):
        return itermelt(self.source, self.key, self.variables, 
                        self.variablefield, self.valuefield)
    

def itermelt(source, key, variables, variablefield, valuefield):
    it = iter(source)
    
    # normalise some stuff
    flds = it.next()
    if isinstance(key, basestring):
        key = (key,) # normalise to a tuple
    if isinstance(variables, basestring):
        # shouldn't expect this, but ... ?
        variables = (variables,) # normalise to a tuple
    if not key:
        # assume key is fields not in variables
        key = [f for f in flds if f not in variables]
    if not variables:
        # assume variables are fields not in key
        variables = [f for f in flds if f not in key]
    
    # determine the output fields
    out_flds = list(key)
    out_flds.append(variablefield)
    out_flds.append(valuefield)
    yield tuple(out_flds)
    
    key_indices = [flds.index(k) for k in key]
    getkey = rowgetter(*key_indices)
    variables_indices = [flds.index(v) for v in variables]
    
    # construct the output data
    for row in it:
        k = getkey(row)
        for v, i in zip(variables, variables_indices):
            o = list(k) # populate with key values initially
            o.append(v) # add variable
            o.append(row[i]) # add value
            yield tuple(o)
            

def recast(table, key=None, variablefield='variable', valuefield='value', 
           samplesize=1000, reducers=None, missing=None):
    """
    Recast molten data. E.g.::
    
        >>> from petl import recast, look
        >>> look(table1)
        +------+------------+---------+
        | 'id' | 'variable' | 'value' |
        +======+============+=========+
        | 3    | 'age'      | 16      |
        +------+------------+---------+
        | 1    | 'gender'   | 'F'     |
        +------+------------+---------+
        | 2    | 'gender'   | 'M'     |
        +------+------------+---------+
        | 2    | 'age'      | 17      |
        +------+------------+---------+
        | 1    | 'age'      | 12      |
        +------+------------+---------+
        | 3    | 'gender'   | 'M'     |
        +------+------------+---------+
        
        >>> table2 = recast(table1)
        >>> look(table2)
        +------+-------+----------+
        | 'id' | 'age' | 'gender' |
        +======+=======+==========+
        | 1    | 12    | 'F'      |
        +------+-------+----------+
        | 2    | 17    | 'M'      |
        +------+-------+----------+
        | 3    | 16    | 'M'      |
        +------+-------+----------+
        
        >>> # specifying variable and value fields
        ... look(table3)
        +------+----------+--------+
        | 'id' | 'vars'   | 'vals' |
        +======+==========+========+
        | 3    | 'age'    | 16     |
        +------+----------+--------+
        | 1    | 'gender' | 'F'    |
        +------+----------+--------+
        | 2    | 'gender' | 'M'    |
        +------+----------+--------+
        | 2    | 'age'    | 17     |
        +------+----------+--------+
        | 1    | 'age'    | 12     |
        +------+----------+--------+
        | 3    | 'gender' | 'M'    |
        +------+----------+--------+
        
        >>> table4 = recast(table3, variablefield='vars', valuefield='vals')
        >>> look(table4)
        +------+-------+----------+
        | 'id' | 'age' | 'gender' |
        +======+=======+==========+
        | 1    | 12    | 'F'      |
        +------+-------+----------+
        | 2    | 17    | 'M'      |
        +------+-------+----------+
        | 3    | 16    | 'M'      |
        +------+-------+----------+
        
        >>> # if there are multiple values for each key/variable pair, and no reducers
        ... # function is provided, then all values will be listed
        ... look(table6)
        +------+--------+------------+---------+
        | 'id' | 'time' | 'variable' | 'value' |
        +======+========+============+=========+
        | 1    | 11     | 'weight'   | 66.4    |
        +------+--------+------------+---------+
        | 1    | 14     | 'weight'   | 55.2    |
        +------+--------+------------+---------+
        | 2    | 12     | 'weight'   | 53.2    |
        +------+--------+------------+---------+
        | 2    | 16     | 'weight'   | 43.3    |
        +------+--------+------------+---------+
        | 3    | 12     | 'weight'   | 34.5    |
        +------+--------+------------+---------+
        | 3    | 17     | 'weight'   | 49.4    |
        +------+--------+------------+---------+
        
        >>> table7 = recast(table6, key='id')
        >>> look(table7)
        +------+--------------+
        | 'id' | 'weight'     |
        +======+==============+
        | 1    | [66.4, 55.2] |
        +------+--------------+
        | 2    | [53.2, 43.3] |
        +------+--------------+
        | 3    | [34.5, 49.4] |
        +------+--------------+
        
        >>> # multiple values can be reduced via an aggregation function
        ... def mean(values):
        ...     return float(sum(values)) / len(values)
        ... 
        >>> table8 = recast(table6, key='id', reducers={'weight': mean})
        >>> look(table8)    
        +------+--------------------+
        | 'id' | 'weight'           |
        +======+====================+
        | 1    | 60.800000000000004 |
        +------+--------------------+
        | 2    | 48.25              |
        +------+--------------------+
        | 3    | 41.95              |
        +------+--------------------+
        
        >>> # missing values are padded with whatever is provided via the missing 
        ... # keyword argument (None by default)
        ... look(table9)
        +------+------------+---------+
        | 'id' | 'variable' | 'value' |
        +======+============+=========+
        | 1    | 'gender'   | 'F'     |
        +------+------------+---------+
        | 2    | 'age'      | 17      |
        +------+------------+---------+
        | 1    | 'age'      | 12      |
        +------+------------+---------+
        | 3    | 'gender'   | 'M'     |
        +------+------------+---------+
        
        >>> table10 = recast(table9, key='id')
        >>> look(table10)
        +------+-------+----------+
        | 'id' | 'age' | 'gender' |
        +======+=======+==========+
        | 1    | 12    | 'F'      |
        +------+-------+----------+
        | 2    | 17    | None     |
        +------+-------+----------+
        | 3    | None  | 'M'      |
        +------+-------+----------+

    Note that the table is scanned once to discover variables, then a second
    time to reshape the data and recast variables as fields. How many rows are
    scanned in the first pass is determined by the `samplesize` argument.
    
    See also :func:`melt`.
    
    """
    
    return RecastView(table, key=key, variablefield=variablefield, 
                      valuefield=valuefield, samplesize=samplesize, 
                      reducers=reducers, missing=missing)
    

class RecastView(RowContainer):
    
    def __init__(self, source, key=None, variablefield='variable', 
                 valuefield='value', samplesize=1000, reducers=None, 
                 missing=None):
        self.source = source
        self.key = key
        self.variablefield = variablefield
        self.valuefield = valuefield
        self.samplesize = samplesize
        if reducers is None:
            self.reducers = dict()
        else:
            self.reducers = reducers
        self.missing = missing
        
    def __iter__(self):
        return iterrecast(self.source, self.key, self.variablefield, 
                          self.valuefield, self.samplesize, self.reducers,
                          self.missing)


def iterrecast(source, key, variablefield, valuefield, 
               samplesize, reducers, missing):        
    #
    # TODO implementing this by making two passes through the data is a bit
    # ugly, and could be costly if there are several upstream transformations
    # that would need to be re-executed each pass - better to make one pass,
    # caching the rows sampled to discover variables to be recast as fields?
    #
    
    
    it = iter(source)
    fields = it.next()
    
    # normalise some stuff
    keyfields = key
    variablefields = variablefield # N.B., could be more than one
    if isinstance(keyfields, basestring):
        keyfields = (keyfields,)
    if isinstance(variablefields, basestring):
        variablefields = (variablefields,)
    if not keyfields:
        # assume keyfields is fields not in variables
        keyfields = [f for f in fields
                     if f not in variablefields and f != valuefield]
    if not variablefields:
        # assume variables are fields not in keyfields
        variablefields = [f for f in fields
                          if f not in keyfields and f != valuefield]
    
    # sanity checks
    assert valuefield in fields, 'invalid value field: %s' % valuefield
    assert valuefield not in keyfields, 'value field cannot be keyfields'
    assert valuefield not in variablefields, \
        'value field cannot be variable field'
    for f in keyfields:
        assert f in fields, 'invalid keyfields field: %s' % f
    for f in variablefields:
        assert f in fields, 'invalid variable field: %s' % f

    # we'll need these later
    valueindex = fields.index(valuefield)
    keyindices = [fields.index(f) for f in keyfields]
    variableindices = [fields.index(f) for f in variablefields]
    
    # determine the actual variable names to be cast as fields
    if isinstance(variablefields, dict):
        # user supplied dictionary
        variables = variablefields
    else:
        variables = defaultdict(set)
        # sample the data to discover variables to be cast as fields
        for row in islice(it, 0, samplesize):
            for i, f in zip(variableindices, variablefields):
                variables[f].add(row[i])
        for f in variables:
            variables[f] = sorted(variables[f]) # turn from sets to sorted lists

    # finished the first pass
        
    # determine the output fields
    outfields = list(keyfields)
    for f in variablefields:
        outfields.extend(variables[f])
    yield tuple(outfields)
    
    # output data
    
    source = sort(source, key=keyfields)
    it = islice(source, 1, None) # skip header row
    getsortablekey = sortable_itemgetter(*keyindices)
    getactualkey = itemgetter(*keyindices)
    
    # process sorted data in newfields
    groups = groupby(it, key=getsortablekey)
    for _, group in groups:
        # may need to iterate over the group more than once
        group = list(group)
        # N.B., key returned by groupby may be wrapped as SortableItem, we want
        # to output the actual key value, get it from the first row in the group
        key_value = getactualkey(group[0])
        if len(keyfields) > 1:
            out_row = list(key_value)
        else:
            out_row = [key_value]
        for f, i in zip(variablefields, variableindices):
            for variable in variables[f]:
                # collect all values for the current variable
                values = [r[valueindex] for r in group if r[i] == variable]
                if len(values) == 0:
                    value = missing
                elif len(values) == 1:
                    value = values[0]
                else:
                    if variable in reducers:
                        redu = reducers[variable]
                    else:
                        redu = list # list all values
                    value = redu(values)
                out_row.append(value)
        yield tuple(out_row)
                
            
def duplicates(table, key=None, presorted=False, buffersize=None, tempdir=None, cache=True):
    """
    Select rows with duplicate values under a given key (or duplicate
    rows where no key is given). E.g.::

        >>> from petl import duplicates, look    
        >>> look(table1)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'A'   | 1     | 2.0   |
        +-------+-------+-------+
        | 'B'   | 2     | 3.4   |
        +-------+-------+-------+
        | 'D'   | 6     | 9.3   |
        +-------+-------+-------+
        | 'B'   | 3     | 7.8   |
        +-------+-------+-------+
        | 'B'   | 2     | 12.3  |
        +-------+-------+-------+
        | 'E'   | None  | 1.3   |
        +-------+-------+-------+
        | 'D'   | 4     | 14.5  |
        +-------+-------+-------+
        
        >>> table2 = duplicates(table1, 'foo')
        >>> look(table2)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'B'   | 2     | 3.4   |
        +-------+-------+-------+
        | 'B'   | 3     | 7.8   |
        +-------+-------+-------+
        | 'B'   | 2     | 12.3  |
        +-------+-------+-------+
        | 'D'   | 6     | 9.3   |
        +-------+-------+-------+
        | 'D'   | 4     | 14.5  |
        +-------+-------+-------+
        
        >>> # compound keys are supported
        ... table3 = duplicates(table1, key=['foo', 'bar'])
        >>> look(table3)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'B'   | 2     | 3.4   |
        +-------+-------+-------+
        | 'B'   | 2     | 12.3  |
        +-------+-------+-------+
        
    If `presorted` is True, it is assumed that the data are already sorted by
    the given key, and the `buffersize`, `tempdir` and `cache` arguments are ignored. Otherwise, the data 
    are sorted, see also the discussion of the `buffersize`, `tempdir` and `cache` arguments under the 
    :func:`sort` function.
    
    See also :func:`unique` and :func:`distinct`.
    
    """

    return DuplicatesView(table, key=key, presorted=presorted, 
                          buffersize=buffersize, tempdir=tempdir, cache=cache)


class DuplicatesView(RowContainer):
    
    def __init__(self, source, key=None, presorted=False, buffersize=None, tempdir=None, cache=True):
        if presorted:
            self.source = source
        else:
            self.source = sort(source, key, buffersize=buffersize, tempdir=tempdir, cache=cache)
        self.key = key # TODO property
        
    def __iter__(self):
        return iterduplicates(self.source, self.key)


def iterduplicates(source, key):
    # assume source is sorted
    # first need to sort the data
    it = iter(source)

    flds = it.next()
    yield tuple(flds)

    # convert field selection into field indices
    if key is None:
        indices = range(len(flds))
    else:
        indices = asindices(flds, key)
        
    # now use field indices to construct a _getkey function
    # N.B., this may raise an exception on short rows, depending on
    # the field selection
    getkey = itemgetter(*indices)
    
    previous = None
    previous_yielded = False
    
    for row in it:
        if previous is None:
            previous = row
        else:
            kprev = getkey(previous)
            kcurr = getkey(row)
            if kprev == kcurr:
                if not previous_yielded:
                    yield tuple(previous)
                    previous_yielded = True
                yield tuple(row)
            else:
                # reset
                previous_yielded = False
            previous = row
    
    
def unique(table, key=None, presorted=False, buffersize=None, tempdir=None, cache=True):
    """
    Select rows with unique values under a given key (or unique rows
    if no key is given). E.g.::

        >>> from petl import unique, look
        >>> look(table1)
        +-------+-------+--------+
        | 'foo' | 'bar' | 'baz'  |
        +=======+=======+========+
        | 'A'   | 1     | 2      |
        +-------+-------+--------+
        | 'B'   | '2'   | '3.4'  |
        +-------+-------+--------+
        | 'D'   | 'xyz' | 9.0    |
        +-------+-------+--------+
        | 'B'   | u'3'  | u'7.8' |
        +-------+-------+--------+
        | 'B'   | '2'   | 42     |
        +-------+-------+--------+
        | 'E'   | None  | None   |
        +-------+-------+--------+
        | 'D'   | 4     | 12.3   |
        +-------+-------+--------+
        | 'F'   | 7     | 2.3    |
        +-------+-------+--------+
        
        >>> table2 = unique(table1, 'foo')
        >>> look(table2)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'A'   | 1     | 2     |
        +-------+-------+-------+
        | 'E'   | None  | None  |
        +-------+-------+-------+
        | 'F'   | 7     | 2.3   |
        +-------+-------+-------+
        
    If `presorted` is True, it is assumed that the data are already sorted by
    the given key, and the `buffersize`, `tempdir` and `cache` arguments are ignored. Otherwise, the data 
    are sorted, see also the discussion of the `buffersize`, `tempdir` and `cache` arguments under the 
    :func:`sort` function.

    .. versionadded:: 0.10

    See also :func:`duplicates` and :func:`distinct`.
    
    """

    return UniqueView(table, key=key, presorted=presorted, 
                      buffersize=buffersize, tempdir=tempdir, cache=cache)


class UniqueView(RowContainer):
    
    def __init__(self, source, key=None, presorted=False, buffersize=None, tempdir=None, cache=True):
        if presorted:
            self.source = source
        else:
            self.source = sort(source, key, buffersize=buffersize, tempdir=tempdir, cache=cache)
        self.key = key # TODO property
        
    def __iter__(self):
        return iterunique(self.source, self.key)


def iterunique(source, key):
    # assume source is sorted
    # first need to sort the data
    it = iter(source)

    flds = it.next()
    yield tuple(flds)

    # convert field selection into field indices
    if key is None:
        indices = range(len(flds))
    else:
        indices = asindices(flds, key)
        
    # now use field indices to construct a _getkey function
    # N.B., this may raise an exception on short rows, depending on
    # the field selection
    getkey = itemgetter(*indices)
    
    prev = it.next()
    prev_key = getkey(prev)
    prev_comp_ne = True
    
    for curr in it:
        curr_key = getkey(curr)
        curr_comp_ne = (curr_key != prev_key)
        if prev_comp_ne and curr_comp_ne:
            yield tuple(prev)
        prev = curr
        prev_key = curr_key
        prev_comp_ne = curr_comp_ne
        
    # last one?
    if prev_comp_ne:
        yield prev
    
    
def conflicts(table, key, missing=None, include=None, exclude=None, 
              presorted=False, buffersize=None, tempdir=None, cache=True):
    """
    Select rows with the same key value but differing in some other field. E.g.::

        >>> from petl import conflicts, look    
        >>> look(table1)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'A'   | 1     | 2.7   |
        +-------+-------+-------+
        | 'B'   | 2     | None  |
        +-------+-------+-------+
        | 'D'   | 3     | 9.4   |
        +-------+-------+-------+
        | 'B'   | None  | 7.8   |
        +-------+-------+-------+
        | 'E'   | None  |       |
        +-------+-------+-------+
        | 'D'   | 3     | 12.3  |
        +-------+-------+-------+
        | 'A'   | 2     | None  |
        +-------+-------+-------+
        
        >>> table2 = conflicts(table1, 'foo')
        >>> look(table2)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'A'   | 1     | 2.7   |
        +-------+-------+-------+
        | 'A'   | 2     | None  |
        +-------+-------+-------+
        | 'D'   | 3     | 9.4   |
        +-------+-------+-------+
        | 'D'   | 3     | 12.3  |
        +-------+-------+-------+
        
    Missing values are not considered conflicts. By default, `None` is treated
    as the missing value, this can be changed via the `missing` keyword 
    argument.

    One or more fields can be ignored when determining conflicts by providing
    the `exclude` keyword argument. Alternatively, fields to use when determining
    conflicts can be specified explicitly with the `include` keyword argument. 

    If `presorted` is True, it is assumed that the data are already sorted by
    the given key, and the `buffersize`, `tempdir` and `cache` arguments are ignored. Otherwise, the data 
    are sorted, see also the discussion of the `buffersize`, `tempdir` and `cache` arguments under the 
    :func:`sort` function.
    
    .. versionchanged:: 0.8
    
    Added the `include` and `exclude` keyword arguments. The `exclude` keyword 
    argument replaces the `ignore` keyword argument in previous versions.
    
    """
    
    return ConflictsView(table, key, missing=missing, exclude=exclude, include=include,
                         presorted=presorted, buffersize=buffersize, tempdir=tempdir, cache=cache)


class ConflictsView(RowContainer):
    
    def __init__(self, source, key, missing=None, exclude=None, include=None, 
                 presorted=False, buffersize=None, tempdir=None, cache=True):
        if presorted:
            self.source = source
        else:
            self.source = sort(source, key, buffersize=buffersize, tempdir=tempdir, cache=cache)
        self.key = key
        self.missing = missing
        self.exclude = exclude
        self.include = include
        
    def __iter__(self):
        return iterconflicts(self.source, self.key, self.missing, self.exclude, 
                             self.include)
    
    
def iterconflicts(source, key, missing, exclude, include):

    # normalise arguments
    if isinstance(exclude, basestring):
        exclude = (exclude,)
    if isinstance(include, basestring):
        include = (include,)

    # exclude overrides include
    if include and exclude:
        include = None
        
    it = iter(source)
    flds = it.next()
    yield tuple(flds)

    # convert field selection into field indices
    indices = asindices(flds, key)
                    
    # now use field indices to construct a _getkey function
    # N.B., this may raise an exception on short rows, depending on
    # the field selection
    getkey = itemgetter(*indices)
    
    previous = None
    previous_yielded = False
    
    for row in it:
        if previous is None:
            previous = row
        else:
            kprev = getkey(previous)
            kcurr = getkey(row)
            if kprev == kcurr:
                # is there a conflict?
                conflict = False
                for x, y, f in zip(previous, row, flds):
                    if (exclude and f not in exclude) or (include and f in include) or (not exclude and not include):
                        if missing not in (x, y) and x != y:
                            conflict = True
                            break
                if conflict:
                    if not previous_yielded:
                        yield tuple(previous)
                        previous_yielded = True
                    yield tuple(row)
            else:
                # reset
                previous_yielded = False
            previous = row
    

def complement(a, b, presorted=False, buffersize=None, tempdir=None, cache=True):
    """
    Return rows in `a` that are not in `b`. E.g.::
    
        >>> from petl import complement, look
        >>> look(a)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'A'   | 1     | True  |
        +-------+-------+-------+
        | 'C'   | 7     | False |
        +-------+-------+-------+
        | 'B'   | 2     | False |
        +-------+-------+-------+
        | 'C'   | 9     | True  |
        +-------+-------+-------+
        
        >>> look(b)
        +-----+-----+-------+
        | 'x' | 'y' | 'z'   |
        +=====+=====+=======+
        | 'B' | 2   | False |
        +-----+-----+-------+
        | 'A' | 9   | False |
        +-----+-----+-------+
        | 'B' | 3   | True  |
        +-----+-----+-------+
        | 'C' | 9   | True  |
        +-----+-----+-------+
        
        >>> aminusb = complement(a, b)
        >>> look(aminusb)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'A'   | 1     | True  |
        +-------+-------+-------+
        | 'C'   | 7     | False |
        +-------+-------+-------+
        
        >>> bminusa = complement(b, a)
        >>> look(bminusa)
        +-----+-----+-------+
        | 'x' | 'y' | 'z'   |
        +=====+=====+=======+
        | 'A' | 9   | False |
        +-----+-----+-------+
        | 'B' | 3   | True  |
        +-----+-----+-------+
        
    Note that the field names of each table are ignored - rows are simply compared
    following a lexical sort. See also the :func:`recordcomplement` function.
    
    If `presorted` is True, it is assumed that the data are already sorted by
    the given key, and the `buffersize`, `tempdir` and `cache` arguments are ignored. Otherwise, the data 
    are sorted, see also the discussion of the `buffersize`, `tempdir` and `cache` arguments under the 
    :func:`sort` function.
    
    """

    return ComplementView(a, b, presorted=presorted, buffersize=buffersize, tempdir=tempdir, cache=cache)


class ComplementView(RowContainer):
    
    def __init__(self, a, b, presorted=False, buffersize=None, tempdir=None, cache=True):
        if presorted:
            self.a = a
            self.b = b
        else:
            self.a = sort(a, buffersize=buffersize, tempdir=tempdir, cache=cache)
            self.b = sort(b, buffersize=buffersize, tempdir=tempdir, cache=cache)
            
    def __iter__(self):
        return itercomplement(self.a, self.b)


def itercomplement(ta, tb):
    # coerce rows to tuples to ensure hashable and comparable
    ita = (tuple(row) for row in iter(ta)) 
    itb = (tuple(row) for row in iter(tb))
    aflds = tuple(str(f) for f in ita.next())
    itb.next() # ignore b fields
    yield aflds

    try:
        a = ita.next()
    except StopIteration:
        debug('a is empty, nothing to yield')
        pass
    else:
        try:
            b = itb.next()
        except StopIteration:
            debug('b is empty, just iterate through a')
            yield a
            for row in ita:
                yield row
        else:
            # we want the elements in a that are not in b
            while True:
                debug('current rows: %r %r', a, b)
                if b is None or SortableItem(a) < SortableItem(b):
                    yield a
                    debug('advance a')
                    try:
                        a = ita.next()
                    except StopIteration:
                        break
                elif a == b:
                    debug('advance both')
                    try:
                        a = ita.next()
                    except StopIteration:
                        break
                    try:
                        b = itb.next()
                    except StopIteration:
                        b = None
                else:
                    debug('advance b')
                    try:
                        b = itb.next()
                    except StopIteration:
                        b = None
        
    
def recordcomplement(a, b, buffersize=None, tempdir=None, cache=True):
    """
    Find records in `a` that are not in `b`. E.g.::
    
        >>> from petl import recordcomplement, look
        >>> look(a)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'A'   | 1     | True  |
        +-------+-------+-------+
        | 'C'   | 7     | False |
        +-------+-------+-------+
        | 'B'   | 2     | False |
        +-------+-------+-------+
        | 'C'   | 9     | True  |
        +-------+-------+-------+
        
        >>> look(b)
        +-------+-------+-------+
        | 'bar' | 'foo' | 'baz' |
        +=======+=======+=======+
        | 2     | 'B'   | False |
        +-------+-------+-------+
        | 9     | 'A'   | False |
        +-------+-------+-------+
        | 3     | 'B'   | True  |
        +-------+-------+-------+
        | 9     | 'C'   | True  |
        +-------+-------+-------+
        
        >>> aminusb = recordcomplement(a, b)
        >>> look(aminusb)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'A'   | 1     | True  |
        +-------+-------+-------+
        | 'C'   | 7     | False |
        +-------+-------+-------+
        
        >>> bminusa = recordcomplement(b, a)
        >>> look(bminusa)
        +-------+-------+-------+
        | 'bar' | 'foo' | 'baz' |
        +=======+=======+=======+
        | 3     | 'B'   | True  |
        +-------+-------+-------+
        | 9     | 'A'   | False |
        +-------+-------+-------+
        
    Note that both tables must have the same set of fields, but that the order
    of the fields does not matter. See also the :func:`complement` function.
    
    See also the discussion of the `buffersize`, `tempdir` and `cache` arguments under the :func:`sort` 
    function.
    
    .. versionadded:: 0.3
    
    """
    
    ha = header(a)
    hb = header(b)
    assert set(ha) == set(hb), 'both tables must have the same set of fields'
    # make sure fields are in the same order
    bv = cut(b, *ha)
    return complement(a, bv, buffersize=buffersize, tempdir=tempdir, cache=cache)


def diff(a, b, presorted=False, buffersize=None, tempdir=None, cache=True):
    """
    Find the difference between rows in two tables. Returns a pair of tables. 
    E.g.::
    
        >>> from petl import diff, look
        >>> look(a)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'A'   | 1     | True  |
        +-------+-------+-------+
        | 'C'   | 7     | False |
        +-------+-------+-------+
        | 'B'   | 2     | False |
        +-------+-------+-------+
        | 'C'   | 9     | True  |
        +-------+-------+-------+
        
        >>> look(b)
        +-----+-----+-------+
        | 'x' | 'y' | 'z'   |
        +=====+=====+=======+
        | 'B' | 2   | False |
        +-----+-----+-------+
        | 'A' | 9   | False |
        +-----+-----+-------+
        | 'B' | 3   | True  |
        +-----+-----+-------+
        | 'C' | 9   | True  |
        +-----+-----+-------+
        
        >>> added, subtracted = diff(a, b)
        >>> # rows in b not in a
        ... look(added)
        +-----+-----+-------+
        | 'x' | 'y' | 'z'   |
        +=====+=====+=======+
        | 'A' | 9   | False |
        +-----+-----+-------+
        | 'B' | 3   | True  |
        +-----+-----+-------+
        
        >>> # rows in a not in b
        ... look(subtracted)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'A'   | 1     | True  |
        +-------+-------+-------+
        | 'C'   | 7     | False |
        +-------+-------+-------+
        
    Convenient shorthand for ``(complement(b, a), complement(a, b))``. See also
    :func:`complement`.

    If `presorted` is True, it is assumed that the data are already sorted by
    the given key, and the `buffersize`, `tempdir` and `cache` arguments are ignored. Otherwise, the data 
    are sorted, see also the discussion of the `buffersize`, `tempdir` and `cache` arguments under the 
    :func:`sort` function.
    
    """

    if not presorted:    
        a = sort(a)
        b = sort(b)
    added = complement(b, a, presorted=True, buffersize=buffersize, tempdir=tempdir, cache=cache)
    subtracted = complement(a, b, presorted=True, buffersize=buffersize, tempdir=tempdir, cache=cache)
    return added, subtracted
    
    
def recorddiff(a, b, buffersize=None, tempdir=None, cache=True):
    """
    Find the difference between records in two tables. E.g.::

        >>> from petl import recorddiff, look    
        >>> look(a)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'A'   | 1     | True  |
        +-------+-------+-------+
        | 'C'   | 7     | False |
        +-------+-------+-------+
        | 'B'   | 2     | False |
        +-------+-------+-------+
        | 'C'   | 9     | True  |
        +-------+-------+-------+
        
        >>> look(b)
        +-------+-------+-------+
        | 'bar' | 'foo' | 'baz' |
        +=======+=======+=======+
        | 2     | 'B'   | False |
        +-------+-------+-------+
        | 9     | 'A'   | False |
        +-------+-------+-------+
        | 3     | 'B'   | True  |
        +-------+-------+-------+
        | 9     | 'C'   | True  |
        +-------+-------+-------+
        
        >>> added, subtracted = recorddiff(a, b)
        >>> look(added)
        +-------+-------+-------+
        | 'bar' | 'foo' | 'baz' |
        +=======+=======+=======+
        | 3     | 'B'   | True  |
        +-------+-------+-------+
        | 9     | 'A'   | False |
        +-------+-------+-------+
        
        >>> look(subtracted)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'A'   | 1     | True  |
        +-------+-------+-------+
        | 'C'   | 7     | False |
        +-------+-------+-------+

    Convenient shorthand for ``(recordcomplement(b, a), recordcomplement(a, b))``. 
    See also :func:`recordcomplement`.

    See also the discussion of the `buffersize`, `tempdir` and `cache` arguments under the :func:`sort` 
    function.
    
    .. versionadded:: 0.3
    
    """

    added = recordcomplement(b, a, buffersize=buffersize, tempdir=tempdir, cache=cache)
    subtracted = recordcomplement(a, b, buffersize=buffersize, tempdir=tempdir, cache=cache)
    return added, subtracted
    
    
def capture(table, field, pattern, newfields=None, include_original=False, 
            flags=0, fill=None):
    """
    Add one or more new fields with values captured from an
    existing field searched via a regular expression. E.g.::

        >>> from petl import capture, look
        >>> look(table1)
        +------+------------+---------+
        | 'id' | 'variable' | 'value' |
        +======+============+=========+
        | '1'  | 'A1'       | '12'    |
        +------+------------+---------+
        | '2'  | 'A2'       | '15'    |
        +------+------------+---------+
        | '3'  | 'B1'       | '18'    |
        +------+------------+---------+
        | '4'  | 'C12'      | '19'    |
        +------+------------+---------+
        
        >>> table2 = capture(table1, 'variable', '(\\w)(\\d+)', ['treat', 'time'])
        >>> look(table2)
        +------+---------+---------+--------+
        | 'id' | 'value' | 'treat' | 'time' |
        +======+=========+=========+========+
        | '1'  | '12'    | 'A'     | '1'    |
        +------+---------+---------+--------+
        | '2'  | '15'    | 'A'     | '2'    |
        +------+---------+---------+--------+
        | '3'  | '18'    | 'B'     | '1'    |
        +------+---------+---------+--------+
        | '4'  | '19'    | 'C'     | '12'   |
        +------+---------+---------+--------+
        
        >>> # using the include_original argument
        ... table3 = capture(table1, 'variable', '(\\w)(\\d+)', ['treat', 'time'], include_original=True)
        >>> look(table3)
        +------+------------+---------+---------+--------+
        | 'id' | 'variable' | 'value' | 'treat' | 'time' |
        +======+============+=========+=========+========+
        | '1'  | 'A1'       | '12'    | 'A'     | '1'    |
        +------+------------+---------+---------+--------+
        | '2'  | 'A2'       | '15'    | 'A'     | '2'    |
        +------+------------+---------+---------+--------+
        | '3'  | 'B1'       | '18'    | 'B'     | '1'    |
        +------+------------+---------+---------+--------+
        | '4'  | 'C12'      | '19'    | 'C'     | '12'   |
        +------+------------+---------+---------+--------+
        
    By default the field on which the capture is performed is omitted. It can
    be included using the `include_original` argument.
    
    See also :func:`split`, :func:`re.search`.

    .. versionchanged:: 0.18

    The ``fill`` parameter can be used to provide a list or tuple of values to use if the regular expression does not
    match. The ``fill`` parameter should contain as many values as there are capturing groups in the regular expression.
    If ``fill`` is ``None`` (default) then a ``petl.transform.TransformError`` will be raised on the first non-matching
    value.

    """
    
    return CaptureView(table, field, pattern,
                       newfields=newfields,
                       include_original=include_original,
                       flags=flags,
                       fill=fill)


class CaptureView(RowContainer):
    
    def __init__(self, source, field, pattern, newfields=None, 
                 include_original=False, flags=0, fill=None):
        self.source = source
        self.field = field
        self.pattern = pattern
        self.newfields = newfields
        self.include_original = include_original
        self.flags = flags
        self.fill = fill
        
    def __iter__(self):
        return itercapture(self.source, self.field, self.pattern, self.newfields, 
                           self.include_original, self.flags, self.fill)


def itercapture(source, field, pattern, newfields, include_original, flags, fill):
    it = iter(source)
    prog = re.compile(pattern, flags)
    
    flds = it.next()
    if field in flds:
        field_index = flds.index(field)
    elif isinstance(field, int) and field < len(flds):
        field_index = field
    else:
        raise Exception('field invalid: must be either field name or index')
    
    # determine output fields
    out_flds = list(flds)
    if not include_original:
        out_flds.remove(field)
    if newfields:   
        out_flds.extend(newfields)
    yield tuple(out_flds)
    
    # construct the output data
    for row in it:
        value = row[field_index]
        if include_original:
            out_row = list(row)
        else:
            out_row = [v for i, v in enumerate(row) if i != field_index]
        match = prog.search(value)
        if match is None:
            if fill is not None:
                out_row.extend(fill)
            else:
                raise TransformError('value %r did not match pattern %r' % (value, pattern))
        else:
            out_row.extend(match.groups())
        yield tuple(out_row)
        
        
def split(table, field, pattern, newfields=None, include_original=False,
          maxsplit=0, flags=0):
    """
    Add one or more new fields with values generated by 
    splitting an existing value around occurrences of a regular expression. 
    E.g.::

        >>> from petl import split, look
        >>> look(table1)
        +------+------------+---------+
        | 'id' | 'variable' | 'value' |
        +======+============+=========+
        | '1'  | 'parad1'   | '12'    |
        +------+------------+---------+
        | '2'  | 'parad2'   | '15'    |
        +------+------------+---------+
        | '3'  | 'tempd1'   | '18'    |
        +------+------------+---------+
        | '4'  | 'tempd2'   | '19'    |
        +------+------------+---------+
        
        >>> table2 = split(table1, 'variable', 'd', ['variable', 'day'])
        >>> look(table2)
        +------+---------+------------+-------+
        | 'id' | 'value' | 'variable' | 'day' |
        +======+=========+============+=======+
        | '1'  | '12'    | 'para'     | '1'   |
        +------+---------+------------+-------+
        | '2'  | '15'    | 'para'     | '2'   |
        +------+---------+------------+-------+
        | '3'  | '18'    | 'temp'     | '1'   |
        +------+---------+------------+-------+
        | '4'  | '19'    | 'temp'     | '2'   |
        +------+---------+------------+-------+
        
    See also :func:`re.split`.

    """
    
    return SplitView(table, field, pattern, newfields, include_original, maxsplit,
                     flags)


class SplitView(RowContainer):
    
    def __init__(self, source, field, pattern, newfields=None, 
                 include_original=False, maxsplit=0, flags=0):
        self.source = source
        self.field = field
        self.pattern = pattern
        self.newfields = newfields
        self.include_original = include_original
        self.maxsplit = maxsplit
        self.flags = flags
        
    def __iter__(self):
        return itersplit(self.source, self.field, self.pattern, self.newfields, 
                         self.include_original, self.maxsplit, self.flags)


def itersplit(source, field, pattern, newfields, include_original, maxsplit,
              flags):
        
    it = iter(source)
    prog = re.compile(pattern, flags)

    flds = it.next()
    if field in flds:
        field_index = flds.index(field)
    elif isinstance(field, int) and field < len(flds):
        field_index = field
        field = flds[field_index]
    else:
        raise Exception('field invalid: must be either field name or index')
    
    # determine output fields
    out_flds = list(flds)
    if not include_original:
        out_flds.remove(field)
    if newfields:
        out_flds.extend(newfields)
    yield tuple(out_flds)
    
    # construct the output data
    for row in it:
        value = row[field_index]
        if include_original:
            out_row = list(row)
        else:
            out_row = [v for i, v in enumerate(row) if i != field_index]
        out_row.extend(prog.split(value, maxsplit))
        yield tuple(out_row)
        
    
def fieldmap(table, mappings=None, failonerror=False, errorvalue=None):
    """
    Transform a table, mapping fields arbitrarily between input and output. E.g.::
    
        >>> from petl import fieldmap, look
        >>> look(table1)
        +------+----------+-------+----------+----------+
        | 'id' | 'sex'    | 'age' | 'height' | 'weight' |
        +======+==========+=======+==========+==========+
        | 1    | 'male'   | 16    | 1.45     | 62.0     |
        +------+----------+-------+----------+----------+
        | 2    | 'female' | 19    | 1.34     | 55.4     |
        +------+----------+-------+----------+----------+
        | 3    | 'female' | 17    | 1.78     | 74.4     |
        +------+----------+-------+----------+----------+
        | 4    | 'male'   | 21    | 1.33     | 45.2     |
        +------+----------+-------+----------+----------+
        | 5    | '-'      | 25    | 1.65     | 51.9     |
        +------+----------+-------+----------+----------+
        
        >>> from collections import OrderedDict
        >>> mappings = OrderedDict()
        >>> # rename a field
        ... mappings['subject_id'] = 'id'
        >>> # translate a field
        ... mappings['gender'] = 'sex', {'male': 'M', 'female': 'F'}
        >>> # apply a calculation to a field
        ... mappings['age_months'] = 'age', lambda v: v * 12
        >>> # apply a calculation to a combination of fields
        ... mappings['bmi'] = lambda rec: rec['weight'] / rec['height']**2 
        >>> # transform and inspect the output
        ... table2 = fieldmap(table1, mappings)
        >>> look(table2)
        +--------------+----------+--------------+--------------------+
        | 'subject_id' | 'gender' | 'age_months' | 'bmi'              |
        +==============+==========+==============+====================+
        | 1            | 'M'      | 192          | 29.48870392390012  |
        +--------------+----------+--------------+--------------------+
        | 2            | 'F'      | 228          | 30.8531967030519   |
        +--------------+----------+--------------+--------------------+
        | 3            | 'F'      | 204          | 23.481883600555488 |
        +--------------+----------+--------------+--------------------+
        | 4            | 'M'      | 252          | 25.55260331279326  |
        +--------------+----------+--------------+--------------------+
        | 5            | '-'      | 300          | 19.0633608815427   |
        +--------------+----------+--------------+--------------------+
        
        >>> # field mappings can also be added and/or updated after the table is created 
        ... # via the suffix notation
        ... table3 = fieldmap(table1)
        >>> table3['subject_id'] = 'id'
        >>> table3['gender'] = 'sex', {'male': 'M', 'female': 'F'}
        >>> table3['age_months'] = 'age', lambda v: v * 12
        >>> # use an expression string this time
        ... table3['bmi'] = '{weight} / {height}**2'
        >>> look(table3)
        +--------------+----------+--------------+--------------------+
        | 'subject_id' | 'gender' | 'age_months' | 'bmi'              |
        +==============+==========+==============+====================+
        | 1            | 'M'      | 192          | 29.48870392390012  |
        +--------------+----------+--------------+--------------------+
        | 2            | 'F'      | 228          | 30.8531967030519   |
        +--------------+----------+--------------+--------------------+
        | 3            | 'F'      | 204          | 23.481883600555488 |
        +--------------+----------+--------------+--------------------+
        | 4            | 'M'      | 252          | 25.55260331279326  |
        +--------------+----------+--------------+--------------------+
        | 5            | '-'      | 300          | 19.0633608815427   |
        +--------------+----------+--------------+--------------------+
        
    Note also that the mapping value can be an expression string, which will be 
    converted to a lambda function via :func:`expr`. 

    """    
    
    return FieldMapView(table, mappings=mappings, failonerror=failonerror,
                        errorvalue=errorvalue)
    
    
class FieldMapView(RowContainer):
    
    def __init__(self, source, mappings=None, failonerror=False, errorvalue=None):
        self.source = source
        if mappings is None:
            self.mappings = OrderedDict()
        else:
            self.mappings = mappings
        self.failonerror = failonerror
        self.errorvalue = errorvalue
        
    def __setitem__(self, key, value):
        self.mappings[key] = value
        
    def __iter__(self):
        return iterfieldmap(self.source, self.mappings, self.failonerror, self.errorvalue)
    
    
def iterfieldmap(source, mappings, failonerror, errorvalue):
    it = iter(source)
    flds = it.next()
    outflds = mappings.keys()
    yield tuple(outflds)
    
    mapfuns = dict()
    for outfld, m in mappings.items():
        if m in flds:
            mapfuns[outfld] = itemgetter(m)
        elif isinstance(m, int) and m < len(flds):
            mapfuns[outfld] = itemgetter(m)
        elif isinstance(m, basestring):
            mapfuns[outfld] = expr(m)
        elif callable(m):
            mapfuns[outfld] = m
        elif isinstance(m, (tuple, list)) and len(m) == 2:
            srcfld = m[0]
            fm = m[1]
            if callable(fm):
                mapfuns[outfld] = composefun(fm, srcfld)
            elif isinstance(fm, dict):
                mapfuns[outfld] = composedict(fm, srcfld)
            else:
                raise Exception('expected callable or dict') # TODO better error
        else:
            raise Exception('invalid mapping', outfld, m) # TODO better error
            
    for row in hybridrows(flds, it):
        try:
            # use list comprehension if possible
            outrow = [mapfuns[outfld](row) for outfld in outflds]
        except:
            # fall back to doing it one field at a time
            outrow = list()
            for outfld in outflds:
                try:
                    val = mapfuns[outfld](row)
                except:
                    if failonerror:
                        raise
                    else:
                        val = errorvalue
                outrow.append(val)
        yield tuple(outrow)
                
        
def composefun(f, srcfld):
    def g(rec):
        return f(rec[srcfld])
    return g


def composedict(d, srcfld):
    def g(rec):
        k = rec[srcfld]
        if k in d:
            return d[k]
        else:
            return k
    return g


def facet(table, field):
    """
    Return a dictionary mapping field values to tables. 
    
    E.g.::
    
        >>> from petl import facet, look
        >>> look(table1)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'a'   | 4     | 9.3   |
        +-------+-------+-------+
        | 'a'   | 2     | 88.2  |
        +-------+-------+-------+
        | 'b'   | 1     | 23.3  |
        +-------+-------+-------+
        | 'c'   | 8     | 42.0  |
        +-------+-------+-------+
        | 'd'   | 7     | 100.9 |
        +-------+-------+-------+
        | 'c'   | 2     |       |
        +-------+-------+-------+
        
        >>> foo = facet(table1, 'foo')
        >>> foo.keys()
        ['a', 'c', 'b', 'd']
        >>> look(foo['a'])
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'a'   | 4     | 9.3   |
        +-------+-------+-------+
        | 'a'   | 2     | 88.2  |
        +-------+-------+-------+
        
        >>> look(foo['c'])
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'c'   | 8     | 42.0  |
        +-------+-------+-------+
        | 'c'   | 2     |       |
        +-------+-------+-------+
        
    See also :func:`facetcolumns`.
    
    """
    
    fct = dict()
    for v in valueset(table, field):
        fct[v] = selecteq(table, field, v)
    return fct


def rowmap(table, rowmapper, fields, failonerror=False, missing=None):
    """
    Transform rows via an arbitrary function. E.g.::

        >>> from petl import rowmap, look
        >>> look(table1)
        +------+----------+-------+----------+----------+
        | 'id' | 'sex'    | 'age' | 'height' | 'weight' |
        +======+==========+=======+==========+==========+
        | 1    | 'male'   | 16    | 1.45     | 62.0     |
        +------+----------+-------+----------+----------+
        | 2    | 'female' | 19    | 1.34     | 55.4     |
        +------+----------+-------+----------+----------+
        | 3    | 'female' | 17    | 1.78     | 74.4     |
        +------+----------+-------+----------+----------+
        | 4    | 'male'   | 21    | 1.33     | 45.2     |
        +------+----------+-------+----------+----------+
        | 5    | '-'      | 25    | 1.65     | 51.9     |
        +------+----------+-------+----------+----------+
        
        >>> def rowmapper(row):
        ...     transmf = {'male': 'M', 'female': 'F'}
        ...     return [row[0],
        ...             transmf[row[1]] if row[1] in transmf else row[1],
        ...             row[2] * 12,
        ...             row[4] / row[3] ** 2]
        ... 
        >>> table2 = rowmap(table1, rowmapper, fields=['subject_id', 'gender', 'age_months', 'bmi'])  
        >>> look(table2)    
        +--------------+----------+--------------+--------------------+
        | 'subject_id' | 'gender' | 'age_months' | 'bmi'              |
        +==============+==========+==============+====================+
        | 1            | 'M'      | 192          | 29.48870392390012  |
        +--------------+----------+--------------+--------------------+
        | 2            | 'F'      | 228          | 30.8531967030519   |
        +--------------+----------+--------------+--------------------+
        | 3            | 'F'      | 204          | 23.481883600555488 |
        +--------------+----------+--------------+--------------------+
        | 4            | 'M'      | 252          | 25.55260331279326  |
        +--------------+----------+--------------+--------------------+
        | 5            | '-'      | 300          | 19.0633608815427   |
        +--------------+----------+--------------+--------------------+

    The `rowmapper` function should return a single row (list or tuple).
    
    .. versionchanged:: 0.9
    
    Hybrid row objects supporting data value access by either position or by 
    field name are now passed to the `rowmapper` function.
    
    """
    
    return RowMapView(table, rowmapper, fields, failonerror=failonerror,
                      missing=missing)
    
    
class RowMapView(RowContainer):
    
    def __init__(self, source, rowmapper, fields, failonerror=False, missing=None):
        self.source = source
        self.rowmapper = rowmapper
        self.fields = fields
        self.failonerror = failonerror
        self.missing = missing
        
    def __iter__(self):
        return iterrowmap(self.source, self.rowmapper, self.fields, self.failonerror,
                          self.missing)

    
def iterrowmap(source, rowmapper, fields, failonerror, missing):
    it = iter(source)
    srcflds = it.next() 
    yield tuple(fields)
    for row in hybridrows(srcflds, it, missing):
        try:
            outrow = rowmapper(row)
            yield tuple(outrow)
        except:
            if failonerror:
                raise
        
        
def recordmap(table, recmapper, fields, failonerror=False):
    """
    Transform records via an arbitrary function. 
    
    .. deprecated:: 0.9
    
    Use :func:`rowmap` insteand.
    
    """
    
    return rowmap(table, recmapper, fields, failonerror=failonerror)
    
    
def rowmapmany(table, rowgenerator, fields, failonerror=False, missing=None):
    """
    Map each input row to any number of output rows via an arbitrary function.
    E.g.::

        >>> from petl import rowmapmany, look    
        >>> look(table1)
        +------+----------+-------+----------+----------+
        | 'id' | 'sex'    | 'age' | 'height' | 'weight' |
        +======+==========+=======+==========+==========+
        | 1    | 'male'   | 16    | 1.45     | 62.0     |
        +------+----------+-------+----------+----------+
        | 2    | 'female' | 19    | 1.34     | 55.4     |
        +------+----------+-------+----------+----------+
        | 3    | '-'      | 17    | 1.78     | 74.4     |
        +------+----------+-------+----------+----------+
        | 4    | 'male'   | 21    | 1.33     |          |
        +------+----------+-------+----------+----------+
        
        >>> def rowgenerator(row):
        ...     transmf = {'male': 'M', 'female': 'F'}
        ...     yield [row[0], 'gender', transmf[row[1]] if row[1] in transmf else row[1]]
        ...     yield [row[0], 'age_months', row[2] * 12]
        ...     yield [row[0], 'bmi', row[4] / row[3] ** 2]
        ... 
        >>> table2 = rowmapmany(table1, rowgenerator, fields=['subject_id', 'variable', 'value'])  
        >>> look(table2)
        +--------------+--------------+--------------------+
        | 'subject_id' | 'variable'   | 'value'            |
        +==============+==============+====================+
        | 1            | 'gender'     | 'M'                |
        +--------------+--------------+--------------------+
        | 1            | 'age_months' | 192                |
        +--------------+--------------+--------------------+
        | 1            | 'bmi'        | 29.48870392390012  |
        +--------------+--------------+--------------------+
        | 2            | 'gender'     | 'F'                |
        +--------------+--------------+--------------------+
        | 2            | 'age_months' | 228                |
        +--------------+--------------+--------------------+
        | 2            | 'bmi'        | 30.8531967030519   |
        +--------------+--------------+--------------------+
        | 3            | 'gender'     | '-'                |
        +--------------+--------------+--------------------+
        | 3            | 'age_months' | 204                |
        +--------------+--------------+--------------------+
        | 3            | 'bmi'        | 23.481883600555488 |
        +--------------+--------------+--------------------+
        | 4            | 'gender'     | 'M'                |
        +--------------+--------------+--------------------+

    The `rowgenerator` function should yield zero or more rows (lists or tuples).
    
    See also the :func:`melt` function.
    
    .. versionchanged:: 0.9
    
    Hybrid row objects supporting data value access by either position or by 
    field name are now passed to the `rowgenerator` function.
    
    """
    
    return RowMapManyView(table, rowgenerator, fields, failonerror=failonerror,
                          missing=missing)
    
    
class RowMapManyView(RowContainer):
    
    def __init__(self, source, rowgenerator, fields, failonerror=False, missing=None):
        self.source = source
        self.rowgenerator = rowgenerator
        self.fields = fields
        self.failonerror = failonerror
        self.missing = missing
        
    def __iter__(self):
        return iterrowmapmany(self.source, self.rowgenerator, self.fields, 
                              self.failonerror, self.missing)
    
    
def iterrowmapmany(source, rowgenerator, fields, failonerror, missing):
    it = iter(source)
    srcflds = it.next() 
    yield tuple(fields)
    for row in hybridrows(srcflds, it, missing):
        try:
            for outrow in rowgenerator(row):
                yield tuple(outrow)
        except:
            if failonerror:
                raise
        
        
def recordmapmany(table, rowgenerator, fields, failonerror=False):
    """
    Map each input row (as a record) to any number of output rows via an 
    arbitrary function. 
    
    .. deprecated:: 0.9
    
    Use :func:`rowmapmany` instead.

    """
    
    return rowmapmany(table, rowgenerator, fields, failonerror=failonerror)
    
    
def skipcomments(table, prefix):
    """
    Skip any row where the first value is a string and starts with 
    `prefix`. E.g.::
    
        >>> from petl import skipcomments, look
        >>> look(table1)
        +---------+-------+-------+
        | '##aaa' | 'bbb' | 'ccc' |
        +=========+=======+=======+
        | '##mmm' |       |       |
        +---------+-------+-------+
        | '#foo'  | 'bar' |       |
        +---------+-------+-------+
        | '##nnn' | 1     |       |
        +---------+-------+-------+
        | 'a'     | 1     |       |
        +---------+-------+-------+
        | 'b'     | 2     |       |
        +---------+-------+-------+
        
        >>> table2 = skipcomments(table1, '##')
        >>> look(table2)
        +--------+-------+
        | '#foo' | 'bar' |
        +========+=======+
        | 'a'    | 1     |
        +--------+-------+
        | 'b'    | 2     |
        +--------+-------+
        
    .. versionadded:: 0.4

    """ 

    return SkipCommentsView(table, prefix)


class SkipCommentsView(RowContainer):
    
    def __init__(self, source, prefix):
        self.source = source
        self.prefix = prefix
        
    def __iter__(self):
        return iterskipcomments(self.source, self.prefix)   


def iterskipcomments(source, prefix):
    return (row for row in source if len(row) > 0 and not(isinstance(row[0], basestring) and row[0].startswith(prefix)))


def movefield(table, field, index):
    """
    Move a field to a new position.

    ..versionadded:: 0.24

    """

    return MoveFieldView(table, field, index)


class MoveFieldView(object):

    def __init__(self, table, field, index, missing=None):
        self.table = table
        self.field = field
        self.index = index
        self.missing = missing

    def __iter__(self):
        it = iter(self.table)

        # determine output fields
        fields = list(it.next())
        newfields = [f for f in fields if f != self.field]
        newfields.insert(self.index, self.field)
        yield tuple(newfields)

        # define a function to transform each row in the source data
        # according to the field selection
        indices = asindices(fields, newfields)
        transform = rowgetter(*indices)

        # construct the transformed data
        for row in it:
            try:
                yield transform(row)
            except IndexError:
                # row is short, let's be kind and fill in any missing fields
                yield tuple(row[i] if i < len(row) else self.missing for i in indices)


def unpack(table, field, newfields=None, include_original=False, missing=None):
    """
    Unpack data values that are lists or tuples. E.g.::
    
        >>> from petl import unpack, look    
        >>> look(table1)
        +-------+------------+
        | 'foo' | 'bar'      |
        +=======+============+
        | 1     | ['a', 'b'] |
        +-------+------------+
        | 2     | ['c', 'd'] |
        +-------+------------+
        | 3     | ['e', 'f'] |
        +-------+------------+
        
        >>> table2 = unpack(table1, 'bar', ['baz', 'quux'])
        >>> look(table2)
        +-------+-------+--------+
        | 'foo' | 'baz' | 'quux' |
        +=======+=======+========+
        | 1     | 'a'   | 'b'    |
        +-------+-------+--------+
        | 2     | 'c'   | 'd'    |
        +-------+-------+--------+
        | 3     | 'e'   | 'f'    |
        +-------+-------+--------+

        >>> table3 = unpack(table1, 'bar', 2)
        >>> look(table3)
        +-------+--------+--------+
        | 'foo' | 'bar1' | 'bar2' |
        +=======+========+========+
        | 1     | 'a'    | 'b'    |
        +-------+--------+--------+
        | 2     | 'c'    | 'd'    |
        +-------+--------+--------+
        | 3     | 'e'    | 'f'    |
        +-------+--------+--------+

    
    See also :func:`unpackdict`.

    .. versionchanged:: 0.23

    This function will attempt to unpack exactly the number of values as given by the number of new fields specified. If
    there are more values than new fields, remaining values will not be unpacked. If there are less values than new
    fields, missing values will be added.
    
    """
    
    return UnpackView(table, field, newfields=newfields, include_original=include_original, missing=missing)


class UnpackView(RowContainer):
    
    def __init__(self, source, field, newfields=None, include_original=False, missing=None):
        self.source = source
        self.field = field
        self.newfields = newfields
        self.include_original = include_original
        self.missing = missing
        
    def __iter__(self):
        return iterunpack(self.source, self.field, self.newfields, self.include_original, self.missing)


def iterunpack(source, field, newfields, include_original, missing):
    it = iter(source)

    flds = it.next()
    if field in flds:
        field_index = flds.index(field)
    elif isinstance(field, int) and field < len(flds):
        field_index = field
        field = flds[field_index]
    else:
        raise Exception('field invalid: must be either field name or index')
    
    # determine output fields
    out_flds = list(flds)
    if not include_original:
        out_flds.remove(field)
    if isinstance(newfields, (list, tuple)):
        out_flds.extend(newfields)
        nunpack = len(newfields)
    elif isinstance(newfields, int):
        nunpack = newfields
        newfields = [str(field) + str(i+1) for i in range(newfields)]
        out_flds.extend(newfields)
    elif newfields is None:
        nunpack = 0
    else:
        raise Exception('newfields argument must be list or tuple of field names, or int (number of values to unpack)')
    yield tuple(out_flds)
    
    # construct the output data
    for row in it:
        value = row[field_index]
        if include_original:
            out_row = list(row)
        else:
            out_row = [v for i, v in enumerate(row) if i != field_index]
        nvals = len(value)
        if nunpack > 0:
            if nvals >= nunpack:
                newvals = value[:nunpack]
            else:
                newvals = list(value) + ([missing] * (nunpack - nvals))
            out_row.extend(newvals)
        yield tuple(out_row)
        
        
def rangefacet(table, field, width, minv=None, maxv=None,
               presorted=False, buffersize=None, tempdir=None, cache=True):
    """
    Return a dictionary mapping ranges to tables. E.g.::
    
        >>> from petl import rangefacet, look
        >>> look(table1)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'a'   | 3     |
        +-------+-------+
        | 'a'   | 7     |
        +-------+-------+
        | 'b'   | 2     |
        +-------+-------+
        | 'b'   | 1     |
        +-------+-------+
        | 'b'   | 9     |
        +-------+-------+
        | 'c'   | 4     |
        +-------+-------+
        | 'd'   | 3     |
        +-------+-------+
        
        >>> rf = rangefacet(table1, 'bar', 2)
        >>> rf.keys()
        [(1, 3), (3, 5), (5, 7), (7, 9)]
        >>> look(rf[(1, 3)])
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'b'   | 2     |
        +-------+-------+
        | 'b'   | 1     |
        +-------+-------+
        
        >>> look(rf[(7, 9)])
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'a'   | 7     |
        +-------+-------+
        | 'b'   | 9     |
        +-------+-------+

    Note that the last bin includes both edges.
    
    """

    # determine minimum and maximum values
    if minv is None and maxv is None:
        minv, maxv = limits(table, field)
    elif minv is None:
        minv = min(itervalues(table, field))
    elif max is None:
        maxv = max(itervalues(table, field))
        
    fct = OrderedDict()
    for binminv in xrange(minv, maxv, width):
        binmaxv = binminv + width
        if binmaxv >= maxv: # final bin
            binmaxv = maxv
            # final bin includes right edge
            fct[(binminv, binmaxv)] = selectrangeopen(table, field, binminv, binmaxv)
        else:
            fct[(binminv, binmaxv)] = selectrangeopenleft(table, field, binminv, binmaxv)

    return fct
    

def transpose(table):
    """
    Transpose rows into columns. E.g.::

        >>> from petl import transpose, look    
        >>> look(table1)
        +------+----------+
        | 'id' | 'colour' |
        +======+==========+
        | 1    | 'blue'   |
        +------+----------+
        | 2    | 'red'    |
        +------+----------+
        | 3    | 'purple' |
        +------+----------+
        | 5    | 'yellow' |
        +------+----------+
        | 7    | 'orange' |
        +------+----------+
        
        >>> table2 = transpose(table1)
        >>> look(table2)
        +----------+--------+-------+----------+----------+----------+
        | 'id'     | 1      | 2     | 3        | 5        | 7        |
        +==========+========+=======+==========+==========+==========+
        | 'colour' | 'blue' | 'red' | 'purple' | 'yellow' | 'orange' |
        +----------+--------+-------+----------+----------+----------+

    See also :func:`recast`.
    
    """
    
    return TransposeView(table)


class TransposeView(RowContainer):
    
    def __init__(self, source):
        self.source = source
        
    def __iter__(self):
        return itertranspose(self.source)


def itertranspose(source):
    fields = header(source)
    its = [iter(source) for _ in fields]
    for i in range(len(fields)):
        yield tuple(row[i] for row in its[i])
        

def intersection(a, b, presorted=False, buffersize=None, tempdir=None, cache=True):
    """
    Return rows in `a` that are also in `b`. E.g.::
    
        >>> from petl import intersection, look
        >>> look(table1)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'A'   | 1     | True  |
        +-------+-------+-------+
        | 'C'   | 7     | False |
        +-------+-------+-------+
        | 'B'   | 2     | False |
        +-------+-------+-------+
        | 'C'   | 9     | True  |
        +-------+-------+-------+
        
        >>> look(table2)
        +-----+-----+-------+
        | 'x' | 'y' | 'z'   |
        +=====+=====+=======+
        | 'B' | 2   | False |
        +-----+-----+-------+
        | 'A' | 9   | False |
        +-----+-----+-------+
        | 'B' | 3   | True  |
        +-----+-----+-------+
        | 'C' | 9   | True  |
        +-----+-----+-------+
        
        >>> table3 = intersection(table1, table2)
        >>> look(table3)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'B'   | 2     | False |
        +-------+-------+-------+
        | 'C'   | 9     | True  |
        +-------+-------+-------+

    If `presorted` is True, it is assumed that the data are already sorted by
    the given key, and the `buffersize`, `tempdir` and `cache` arguments are ignored. Otherwise, the data 
    are sorted, see also the discussion of the `buffersize`, `tempdir` and `cache` arguments under the 
    :func:`sort` function.
    
    """
    
    return IntersectionView(a, b, presorted, buffersize)


class IntersectionView(RowContainer):
    
    def __init__(self, a, b, presorted=False, buffersize=None, tempdir=None, cache=True):
        if presorted:
            self.a = a
            self.b = b
        else:
            self.a = sort(a, buffersize=buffersize, tempdir=tempdir, cache=cache)
            self.b = sort(b, buffersize=buffersize, tempdir=tempdir, cache=cache)
            
    def __iter__(self):
        return iterintersection(self.a, self.b)


def iterintersection(a, b):
    ita = iter(a) 
    itb = iter(b)
    aflds = ita.next()
    itb.next() # ignore b fields
    yield tuple(aflds)
    try:
        a = tuple(ita.next())
        b = tuple(itb.next())
        while True:
            if a < b:
                a = tuple(ita.next())
            elif a == b:
                yield a
                a = tuple(ita.next())
                b = tuple(itb.next())
            else:
                b = tuple(itb.next())
    except StopIteration:
        pass
    
    
def pivot(table, f1, f2, f3, aggfun, missing=None, 
          presorted=False, buffersize=None, tempdir=None, cache=True):
    """
    Construct a pivot table. E.g.::

        >>> from petl import pivot, look
        >>> look(table1)
        +----------+----------+---------+---------+
        | 'region' | 'gender' | 'style' | 'units' |
        +==========+==========+=========+=========+
        | 'east'   | 'boy'    | 'tee'   | 12      |
        +----------+----------+---------+---------+
        | 'east'   | 'boy'    | 'golf'  | 14      |
        +----------+----------+---------+---------+
        | 'east'   | 'boy'    | 'fancy' | 7       |
        +----------+----------+---------+---------+
        | 'east'   | 'girl'   | 'tee'   | 3       |
        +----------+----------+---------+---------+
        | 'east'   | 'girl'   | 'golf'  | 8       |
        +----------+----------+---------+---------+
        | 'east'   | 'girl'   | 'fancy' | 18      |
        +----------+----------+---------+---------+
        | 'west'   | 'boy'    | 'tee'   | 12      |
        +----------+----------+---------+---------+
        | 'west'   | 'boy'    | 'golf'  | 15      |
        +----------+----------+---------+---------+
        | 'west'   | 'boy'    | 'fancy' | 8       |
        +----------+----------+---------+---------+
        | 'west'   | 'girl'   | 'tee'   | 6       |
        +----------+----------+---------+---------+
        
        >>> table2 = pivot(table1, 'region', 'gender', 'units', sum)
        >>> look(table2)
        +----------+-------+--------+
        | 'region' | 'boy' | 'girl' |
        +==========+=======+========+
        | 'east'   | 33    | 29     |
        +----------+-------+--------+
        | 'west'   | 35    | 23     |
        +----------+-------+--------+
        
        >>> table3 = pivot(table1, 'region', 'style', 'units', sum)
        >>> look(table3)
        +----------+---------+--------+-------+
        | 'region' | 'fancy' | 'golf' | 'tee' |
        +==========+=========+========+=======+
        | 'east'   | 25      | 22     | 15    |
        +----------+---------+--------+-------+
        | 'west'   | 9       | 31     | 18    |
        +----------+---------+--------+-------+
        
        >>> table4 = pivot(table1, 'gender', 'style', 'units', sum)
        >>> look(table4)
        +----------+---------+--------+-------+
        | 'gender' | 'fancy' | 'golf' | 'tee' |
        +==========+=========+========+=======+
        | 'boy'    | 15      | 29     | 24    |
        +----------+---------+--------+-------+
        | 'girl'   | 19      | 24     | 9     |
        +----------+---------+--------+-------+
        
    See also :func:`recast`.

    """
    
    return PivotView(table, f1, f2, f3, aggfun, missing=missing, 
                     presorted=presorted, buffersize=buffersize, tempdir=tempdir,
                     cache=cache)


class PivotView(RowContainer):
    
    def __init__(self, source, f1, f2, f3, aggfun, missing=None, 
                 presorted=False, buffersize=None, tempdir=None, cache=True):
        if presorted:
            self.source = source
        else:
            self.source = sort(source, key=(f1, f2), buffersize=buffersize, tempdir=tempdir, cache=cache)
        self.f1, self.f2, self.f3 = f1, f2, f3
        self.aggfun = aggfun
        self.missing = missing
        
    def __iter__(self):
        return iterpivot(self.source, self.f1, self.f2, self.f3, self.aggfun, self.missing)
    
    
def iterpivot(source, f1, f2, f3, aggfun, missing):
    
    # first pass - collect fields
    f2vals = set(itervalues(source, f2)) # TODO sampling
    f2vals = list(f2vals)
    f2vals.sort()
    outflds = [f1]
    outflds.extend(f2vals)
    yield tuple(outflds)
    
    # second pass - generate output
    it = iter(source)
    srcflds = it.next()
    f1i = srcflds.index(f1)
    f2i = srcflds.index(f2)
    f3i = srcflds.index(f3)
    for v1, v1rows in groupby(it, key=itemgetter(f1i)):
        outrow = [v1] + [missing] * len(f2vals)
        for v2, v12rows in groupby(v1rows, key=itemgetter(f2i)):
            aggval = aggfun([row[f3i] for row in v12rows])
            outrow[1 + f2vals.index(v2)] = aggval
        yield tuple(outrow) 
    
    
def flatten(table):
    """
    Convert a table to a sequence of values in row-major order. E.g.::

        >>> from petl import flatten, look
        >>> look(table1)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'A'   | 1     | True  |
        +-------+-------+-------+
        | 'C'   | 7     | False |
        +-------+-------+-------+
        | 'B'   | 2     | False |
        +-------+-------+-------+
        | 'C'   | 9     | True  |
        +-------+-------+-------+
        
        >>> list(flatten(table1))
        ['A', 1, True, 'C', 7, False, 'B', 2, False, 'C', 9, True]
    
    See also :func:`unflatten`.
    
    .. versionadded:: 0.7
    
    """
    
    return FlattenView(table)


class FlattenView(RowContainer):
    
    def __init__(self, table):
        self.table = table
        
    def __iter__(self):
        for row in data(self.table):
            for value in row:
                yield value
    
    
def unflatten(*args, **kwargs):
    """
    Convert a sequence of values in row-major order into a table. E.g.::
    
        >>> from petl import unflatten, look
        >>> input = ['A', 1, True, 'C', 7, False, 'B', 2, False, 'C', 9]
        >>> table = unflatten(input, 3)
        >>> look(table)
        +------+------+-------+
        | 'f0' | 'f1' | 'f2'  |
        +======+======+=======+
        | 'A'  | 1    | True  |
        +------+------+-------+
        | 'C'  | 7    | False |
        +------+------+-------+
        | 'B'  | 2    | False |
        +------+------+-------+
        | 'C'  | 9    | None  |
        +------+------+-------+
        
        >>> # a table and field name can also be provided as arguments
        ... look(table1)
        +---------+
        | 'lines' |
        +=========+
        | 'A'     |
        +---------+
        | 1       |
        +---------+
        | True    |
        +---------+
        | 'C'     |
        +---------+
        | 7       |
        +---------+
        | False   |
        +---------+
        | 'B'     |
        +---------+
        | 2       |
        +---------+
        | False   |
        +---------+
        | 'C'     |
        +---------+
        
        >>> table2 = unflatten(table1, 'lines', 3)
        >>> look(table2)
        +------+------+-------+
        | 'f0' | 'f1' | 'f2'  |
        +======+======+=======+
        | 'A'  | 1    | True  |
        +------+------+-------+
        | 'C'  | 7    | False |
        +------+------+-------+
        | 'B'  | 2    | False |
        +------+------+-------+
        | 'C'  | 9    | None  |
        +------+------+-------+
        
    See also :func:`flatten`.
    
    .. versionadded:: 0.7
    
    """
    
    return UnflattenView(*args, **kwargs)


class UnflattenView(RowContainer):
    
    def __init__(self, *args, **kwargs):
        if len(args) == 2:
            self.input = args[0]
            self.period = args[1]
        elif len(args) == 3:
            self.input = values(args[0], args[1])
            self.period = args[2]
        else:
            assert False, 'invalid arguments'
        self.missing = kwargs.get('missing', None)
        
    def __iter__(self):
        inpt = self.input
        period = self.period
        missing = self.missing
        
        # generate header row
        fields = tuple('f%s' % i for i in range(period))
        yield fields
        
        # generate data rows
        row = list()
        for v in inpt:
            if len(row) < period:
                row.append(v)
            else:
                yield tuple(row)
                row = [v]
        
        # deal with last row
        if len(row) > 0:
            if len(row) < period:
                row.extend([missing] * (period - len(row)))
            yield tuple(row)
            

def annex(*tables, **kwargs):
    """
    Join two or more tables by row order. E.g.::

        >>> from petl import annex, look
        >>> look(table1)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'A'   | 9     |
        +-------+-------+
        | 'C'   | 2     |
        +-------+-------+
        | 'F'   | 1     |
        +-------+-------+
        
        >>> look(table2)
        +-------+-------+
        | 'foo' | 'baz' |
        +=======+=======+
        | 'B'   | 3     |
        +-------+-------+
        | 'D'   | 10    |
        +-------+-------+
        
        >>> table3 = annex(table1, table2)
        >>> look(table3)    
        +-------+-------+-------+-------+
        | 'foo' | 'bar' | 'foo' | 'baz' |
        +=======+=======+=======+=======+
        | 'A'   | 9     | 'B'   | 3     |
        +-------+-------+-------+-------+
        | 'C'   | 2     | 'D'   | 10    |
        +-------+-------+-------+-------+
        | 'F'   | 1     | None  | None  |
        +-------+-------+-------+-------+

    .. versionadded:: 0.10
    
    """
    
    return AnnexView(tables, **kwargs)


class AnnexView(RowContainer):
    
    def __init__(self, tables, missing=None):
        self.tables = tables
        self.missing = missing
        
    def __iter__(self):
        return iterannex(self.tables, self.missing)
    

def iterannex(tables, missing):
    iters = [iter(t) for t in tables]
    headers = [it.next() for it in iters]
    outfields = tuple(chain(*headers))  
    yield outfields
    for rows in izip_longest(*iters):
        outrow = list()
        for i, row in enumerate(rows):
            lh = len(headers[i])
            if row is None: # handle uneven length tables
                row = [missing] * len(headers[i])
            else:
                lr = len(row)
                if lr < lh: # handle short rows
                    row = list(row)
                    row.extend([missing] * (lh-lr))
                elif lr > lh: # handle long rows
                    row = row[:lh]
            outrow.extend(row)
        yield tuple(outrow)
          
    
def unpackdict(table, field, keys=None, includeoriginal=False,
               samplesize=1000, missing=None):
    """
    Unpack dictionary values into separate fields. E.g.::
    
        >>> from petl import unpackdict, look
        >>> look(table1)
        +-------+---------------------------+
        | 'foo' | 'bar'                     |
        +=======+===========================+
        | 1     | {'quux': 'b', 'baz': 'a'} |
        +-------+---------------------------+
        | 2     | {'quux': 'd', 'baz': 'c'} |
        +-------+---------------------------+
        | 3     | {'quux': 'f', 'baz': 'e'} |
        +-------+---------------------------+
        
        >>> table2 = unpackdict(table1, 'bar')
        >>> look(table2)
        +-------+-------+--------+
        | 'foo' | 'baz' | 'quux' |
        +=======+=======+========+
        | 1     | 'a'   | 'b'    |
        +-------+-------+--------+
        | 2     | 'c'   | 'd'    |
        +-------+-------+--------+
        | 3     | 'e'   | 'f'    |
        +-------+-------+--------+

    .. versionadded:: 0.10
    
    """
    
    return UnpackDictView(table, field, keys=keys, 
                          includeoriginal=includeoriginal,
                          samplesize=samplesize, missing=missing)


class UnpackDictView(RowContainer):

    def __init__(self, table, field, keys=None, includeoriginal=False,
                 samplesize=1000, missing=None):
        self.table = table
        self.field = field
        self.keys = keys
        self.includeoriginal = includeoriginal
        self.samplesize = samplesize
        self.missing = missing

    def __iter__(self):
        return iterunpackdict(self.table, self.field, self.keys, 
                              self.includeoriginal, self.samplesize,
                              self.missing)
    

def iterunpackdict(table, field, keys, includeoriginal, samplesize, missing):

    # set up
    it = iter(table)
    fields = it.next()
    fidx = fields.index(field)
    outfields = list(fields)
    if not includeoriginal:
        del outfields[fidx]

    # are keys specified?
    if not keys:
        # need to sample to find keys
        sample = list(islice(it, samplesize))
        keys = set()
        for row in sample:
            try:
                keys |= set(row[fidx].keys())
            except AttributeError:
                pass
        it = chain(sample, it)
        keys = sorted(keys)
    outfields.extend(keys)
    yield tuple(outfields)    
        
    # generate the data rows
    for row in it:
        outrow = list(row)
        if not includeoriginal:
            del outrow[fidx]
        for key in keys:
            try:
                outrow.append(row[fidx][key])
            except:
                outrow.append(missing)
        yield tuple(outrow)
        

def fold(table, key, f, value=None, presorted=False, buffersize=None, tempdir=None, cache=True):
    """
    Reduce rows recursively via the Python standard :func:`reduce` function. E.g.::

        >>> from petl import fold, look
        >>> look(table1)
        +------+---------+
        | 'id' | 'count' |
        +======+=========+
        | 1    | 3       |
        +------+---------+
        | 1    | 5       |
        +------+---------+
        | 2    | 4       |
        +------+---------+
        | 2    | 8       |
        +------+---------+
        
        >>> import operator
        >>> table2 = fold(table1, 'id', operator.add, 'count', presorted=True)
        >>> look(table2)
        +-------+---------+
        | 'key' | 'value' |
        +=======+=========+
        | 1     | 8       |
        +-------+---------+
        | 2     | 12      |
        +-------+---------+

    See also :func:`aggregate`, :func:`rowreduce`.
    
    .. versionadded:: 0.10
    
    """
    
    return FoldView(table, key, f, value=value, presorted=presorted, 
                    buffersize=buffersize, tempdir=tempdir, cache=cache)
    

class FoldView(RowContainer):
    
    def __init__(self, table, key, f, value=None, presorted=False, 
                 buffersize=None, tempdir=None, cache=True):
        if presorted:
            self.table = table
        else:
            self.table = sort(table, key, buffersize=buffersize, tempdir=tempdir, cache=cache)
        self.key = key
        self.f = f
        self.value = value
        
    def __iter__(self):
        return iterfold(self.table, self.key, self.f, self.value)
    

def iterfold(table, key, f, value):
    yield ('key', 'value')
    for k, grp in rowgroupby(table, key, value):
        yield k, reduce(f, grp)


def addrownumbers(table, start=1, step=1):
    """
    Add a field of row numbers. E.g.::

        >>> from petl import addrownumbers, look
        >>> look(table1)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'A'   | 9     |
        +-------+-------+
        | 'C'   | 2     |
        +-------+-------+
        | 'F'   | 1     |
        +-------+-------+
        
        >>> table2 = addrownumbers(table1)
        >>> look(table2)
        +-------+-------+-------+
        | 'row' | 'foo' | 'bar' |
        +=======+=======+=======+
        | 1     | 'A'   | 9     |
        +-------+-------+-------+
        | 2     | 'C'   | 2     |
        +-------+-------+-------+
        | 3     | 'F'   | 1     |
        +-------+-------+-------+

    .. versionadded:: 0.10
    
    """
    
    return AddRowNumbersView(table, start, step)


class AddRowNumbersView(RowContainer):
    
    def __init__(self, table, start=1, step=1):
        self.table = table
        self.start = start
        self.step = step

    def __iter__(self):
        return iteraddrownumbers(self.table, self.start, self.step)
    

def iteraddrownumbers(table, start, step):
    it = iter(table)
    flds = it.next()
    outflds = ['row']
    outflds.extend(flds)
    yield tuple(outflds)
    for row, n in izip(it, count(start, step)):
        outrow = [n]
        outrow.extend(row)
        yield tuple(outrow)
        

def search(table, *args, **kwargs):
    """
    Perform a regular expression search, returning rows that match a given
    pattern, either anywhere in the row or within a specific field. E.g.::

        >>> from petl import search, look
        >>> look(table1)
        +------------+-------+--------------------------+
        | 'foo'      | 'bar' | 'baz'                    |
        +============+=======+==========================+
        | 'orange'   | 12    | 'oranges are nice fruit' |
        +------------+-------+--------------------------+
        | 'mango'    | 42    | 'I like them'            |
        +------------+-------+--------------------------+
        | 'banana'   | 74    | 'lovely too'             |
        +------------+-------+--------------------------+
        | 'cucumber' | 41    | 'better than mango'      |
        +------------+-------+--------------------------+
        
        >>> # search any field
        ... table2 = search(table1, '.g.')
        >>> look(table2)
        +------------+-------+--------------------------+
        | 'foo'      | 'bar' | 'baz'                    |
        +============+=======+==========================+
        | 'orange'   | 12    | 'oranges are nice fruit' |
        +------------+-------+--------------------------+
        | 'mango'    | 42    | 'I like them'            |
        +------------+-------+--------------------------+
        | 'cucumber' | 41    | 'better than mango'      |
        +------------+-------+--------------------------+
        
        >>> # search a specific field
        ... table3 = search(table1, 'foo', '.g.')
        >>> look(table3)
        +----------+-------+--------------------------+
        | 'foo'    | 'bar' | 'baz'                    |
        +==========+=======+==========================+
        | 'orange' | 12    | 'oranges are nice fruit' |
        +----------+-------+--------------------------+
        | 'mango'  | 42    | 'I like them'            |
        +----------+-------+--------------------------+
        
    
    .. versionadded:: 0.10
    
    """
    
    if len(args) == 1:
        field = None
        pattern = args[0]
    elif len(args) == 2:
        field = args[0]
        pattern = args[1]
    else:
        raise Exception('expected 1 or 2 arguments')
    return SearchView(table, pattern, field=field, **kwargs)


class SearchView(RowContainer):
    
    def __init__(self, table, pattern, field=None, flags=0):
        self.table = table
        self.pattern = pattern
        self.field = field
        self.flags = flags
        
    def __iter__(self):
        return itersearch(self.table, self.pattern, self.field, self.flags)
    
    
def itersearch(table, pattern, field, flags):
    prog = re.compile(pattern, flags)
    it = iter(table)
    fields = [str(f) for f in it.next()]
    yield tuple(fields)
    
    if field is None:
        # search whole row
        test = lambda row: any(prog.search(str(v)) for v in row)
    elif isinstance(field, basestring):
        # search single field
        index = fields.index(field)
        test = lambda row: prog.search(str(row[index]))
    else: # list or tuple or ...
        # search selection of fields
        indices = asindices(fields, field)
        getvals = itemgetter(*indices)
        test = lambda row: any(prog.search(str(v)) for v in getvals(row))

    for row in it:
        if test(row):
            yield tuple(row)
        
            
def addcolumn(table, field, col, index=None, missing=None):
    """
    Add a column of data to the table. E.g.::
    
        >>> from petl import addcolumn, look
        >>> look(table1)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'A'   | 1     |
        +-------+-------+
        | 'B'   | 2     |
        +-------+-------+
        
        >>> col = [True, False]
        >>> table2 = addcolumn(table1, 'baz', col)
        >>> look(table2)
        +-------+-------+-------+
        | 'foo' | 'bar' | 'baz' |
        +=======+=======+=======+
        | 'A'   | 1     | True  |
        +-------+-------+-------+
        | 'B'   | 2     | False |
        +-------+-------+-------+
    
    .. versionadded:: 0.10
    
    """
    
    return AddColumnView(table, field, col, index=index, missing=missing)


class AddColumnView(RowContainer):
    
    def __init__(self, table, field, col, index=None, missing=None):
        self._table = table
        self._field = field
        self._col = col
        self._index = index
        self._missing = missing
        
    def __iter__(self):
        return iteraddcolumn(self._table, self._field, self._col, 
                             self._index, self._missing)
    
    
def iteraddcolumn(table, field, col, index, missing):
    it = iter(table)
    fields = [str(f) for f in it.next()]
    
    # determine position of new column
    if index is None:
        index = len(fields)
    
    # construct output header
    outflds = list(fields)
    outflds.insert(index, field)
    yield tuple(outflds)
    
    # construct output data
    for row, val in izip_longest(it, col, fillvalue=missing):
        # run out of rows?
        if row == missing:
            row = [missing] * len(fields)
        outrow = list(row)
        outrow.insert(index, val)
        yield tuple(outrow)
        
        
def rowgroupmap(table, key, mapper, fields=None, missing=None, presorted=False,
                buffersize=None, tempdir=None, cache=True):
    """
    Group rows under the given key then apply `mapper` to yield zero or more
    output rows for each input group of rows. 
    
    .. versionadded:: 0.12
    
    """

    return RowGroupMapView(table, key, mapper, fields=fields,
                           presorted=presorted, 
                           buffersize=buffersize, tempdir=tempdir, cache=cache)


class RowGroupMapView(RowContainer):
    
    def __init__(self, source, key, mapper, fields=None, 
                 presorted=False, buffersize=None, tempdir=None, cache=True):
        if presorted:
            self.source = source
        else:
            self.source = sort(source, key, buffersize=buffersize,
                               tempdir=tempdir, cache=cache)
        self.key = key
        self.fields = fields
        self.mapper = mapper

    def __iter__(self):
        return iterrowgroupmap(self.source, self.key, self.mapper, self.fields)

    
def iterrowgroupmap(source, key, mapper, fields):
    yield tuple(fields)
    for key, rows in rowgroupby(source, key):
        for row in mapper(key, rows):
            yield row
        

def distinct(table, presorted=False, buffersize=None, tempdir=None, cache=True):
    """
    Return only distinct rows in the table. See also :func:`duplicates` and
    :func:`unique`.
    
    .. versionadded:: 0.12
    
    """
    
    return DistinctView(table, presorted=presorted, buffersize=buffersize, tempdir=tempdir, cache=cache)


class DistinctView(RowContainer):
    
    def __init__(self, table, presorted=False, buffersize=None, tempdir=None, cache=True):
        if presorted:
            self.table = table
        else:
            self.table = sort(table, buffersize=buffersize, tempdir=tempdir, cache=cache)
        
    def __iter__(self):
        it = iter(self.table)
        yield it.next()
        previous = None
        for row in it:
            if row != previous:
                yield row
            previous = row
            
            
def coalesce(*fields, **kwargs):
    try:
        missing = kwargs['missing']
    except:
        missing = None
    try:
        default = kwargs['default']
    except:
        default = None
    def _coalesce(row):
        for f in fields:
            v = row[f]
            if v is not missing:
                return v
        return default
    return _coalesce
            

class TransformError(Exception):
    pass


def addfieldusingcontext(table, field, query):
    """
    Like :func:`addfield` but the `query` function is passed the previous,
    current and next rows, so values may be calculated based on data in adjacent
    rows.

        >>> from petl import look, addfieldusingcontext
        >>> look(table1)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'A'   |     1 |
        +-------+-------+
        | 'B'   |     4 |
        +-------+-------+
        | 'C'   |     5 |
        +-------+-------+
        | 'D'   |     9 |
        +-------+-------+

        >>> def upstream(prv, cur, nxt):
        ...     if prv is None:
        ...         return None
        ...     else:
        ...         return cur.bar - prv.bar
        ...
        >>> def downstream(prv, cur, nxt):
        ...     if nxt is None:
        ...         return None
        ...     else:
        ...         return nxt.bar - cur.bar
        ...
        >>> table2 = addfieldusingcontext(table1, 'baz', upstream)
        >>> table3 = addfieldusingcontext(table2, 'quux', downstream)
        >>> look(table3)
        +-------+-------+-------+--------+
        | 'foo' | 'bar' | 'baz' | 'quux' |
        +=======+=======+=======+========+
        | 'A'   |     1 | None  |      3 |
        +-------+-------+-------+--------+
        | 'B'   |     4 |     3 |      1 |
        +-------+-------+-------+--------+
        | 'C'   |     5 |     1 |      4 |
        +-------+-------+-------+--------+
        | 'D'   |     9 |     4 | None   |
        +-------+-------+-------+--------+

    .. versionadded:: 0.24

    """

    return AddFieldUsingContextView(table, field, query)


class AddFieldUsingContextView(object):

    def __init__(self, table, field, query):
        self.table = table
        self.field = field
        self.query = query

    def __iter__(self):
        return iteraddfieldusingcontext(self.table, self.field, self.query)


def iteraddfieldusingcontext(table, field, query):
    it = iter(table)
    fields = tuple(it.next())
    yield fields + (field,)
    it = hybridrows(fields, it)
    prv = None
    cur = it.next()
    for nxt in it:
        v = query(prv, cur, nxt)
        yield tuple(cur) + (v,)
        prv = cur
        cur = nxt
    # handle last row
    v = query(prv, cur, None)
    yield tuple(cur) + (v,)
