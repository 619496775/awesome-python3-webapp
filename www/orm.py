import asyncio, logging

import aiomysql

#设置调试级别level,此处为logging.INFO,不设置logging.info()没有任何作用等同于pass
logging.basicConfig(level=logging.INFO)
#一层对logging.info的封装,目的是方便的输出sql语句
def log(sql, args=()):
    logging.info('SQL: %s' % sql)
# 创建连接池

@asyncio.coroutine
def create_pool(loop, **kw):  # **表示将字典扩展为关键字参数,相当于host=xxx,db=yyy....
    logging.info('creat database connection pool...')
    global __pool
    __pool = yield from aiomysql.create_pool(
        host = kw.get('host','localhost'),
        port = kw.get('port',3306),
        user = kw['user'],
        password = kw['password'],
        db = kw['db'],
        # 这个必须设置,否则,从数据库获取到的结果是乱码的
        charset = kw.get('charset','utf8'),
        # 是否自动提交事务,在增删改数据库数据时,如果为True,不需要再commit来提交事务了
        autocommit = kw.get('autocommit',True),
        maxsize = kw.get('maxsize',10),
        minsize = kw.get('minsize',1),
        loop = loop
    )

# select 要执行Select语句，用select函数执行，需要传入SQL语句和SQL参数
# 该协程封装的是查询事务,第一个参数为sql语句,第二个为sql语句中占位符的参数列表,第三个参数是要查询数据的数量
@asyncio.coroutine
def select(sql, args, size=None):
    log(sql,args)
    global __pool
    # 获取数据库连接
    with (yield from __pool) as conn:
        # 获取游标,默认游标返回的结果为元组,每一项是另一个元组,这里可以指定元组的元素为字典通过aiomysql.DictCursor
        cur = yield from conn.cursor(aiomysql.DictCursor)
        # 调用游标的execute()方法来执行sql语句,execute()接收两个参数,第一个为sql语句可以包含占位符,第二个为占位符对应的值,使用该形式可以避免直接使用字符串拼接出来的sql的注入攻击
        # sql语句的占位符为?,mysql里为%s,做替换
        yield from cur.execute(sql.replace('?','%s'),args or ())
        # size有值就获取对应数量的数据
        if size:
            rs = yield from cur.fetchmany(size)
        else:
            # 获取所有数据库中的所有数据,此处返回的是一个数组,数组元素为字典
            rs = yield from cur.fetchall()
        yield from cur.close()
        logging.info('rows returned: %s' % len(rs))
        return rs
    '''
    SQL语句的占位符是?，而MySQL的占位符是%s，select()函数在内部自动替换。注意要始终坚持使用带参数的SQL，而不是自己拼接SQL字符串，这样可以防止SQL注入攻击。

    注意到yield from将调用一个子协程（也就是在一个协程中调用另一个协程）并直接获得子协程的返回结果。

    如果传入size参数，就通过fetchmany()获取最多指定数量的记录，否则，通过fetchall()获取所有记录。

    '''

# Insert,Update,Delete  要执行INSERT、UPDATE、DELETE语句，可以定义一个通用的execute()函数，因为这3种SQL的执行都需要相同的参数，以及返回一个整数表示影响的行数：
async def execute(sql, args, autocommit=True):
    log(sql)
    async with __pool.get() as conn:
        if not autocommit:
            # 如果不是自动提交事务,需要手动启动,但是我发现这个是可以省略的
            await conn.begin()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql.replace('?', '%s'), args)
                # 获取增删改影响的行数
                affected = cur.rowcount
            if not autocommit:
                # 回滚,在执行commit()之前如果出现错误,就回滚到执行事务前的状态,以免影响数据库的完整性
                await conn.commit()
        except BaseException as e:
            if not autocommit:
                # 一直没搞懂yield和await的区别在哪？？？？？？？？
                await conn.rollback()
            raise
        return affected
    '''
    execute()函数和select()函数所不同的是，cursor对象不返回结果集，而是通过rowcount返回结果数。
    '''

'''
ORM(对象关系映射 Object Relational Mapping) 有了基本的select()和execute()函数，我们就可以开始编写一个简单的ORM了。
设计ORM需要从上层调用这角度来设计。
我们先考虑一个User对象，然后把数据库表users和它关联起来。

from orm import Model, StringField, IntegerField

class User(Model):
    __table__ = 'users'

    id = IntegerField(primary_key=True)
    name = StringField()

注意到定义在User类中的__table__、id和name是类的属性，不是实例的属性。所以，在类级别上定义的属性用来描述User对象和
表的映射关系，而实例属性必须通过__init__()方法去初始化，所以两者互不干扰：
# 创建实例：
user = User(id = 123, name = 'Michael')
# 存入数据库：
user.insert()
# 查询所有User对象：
users = User.findAll()
'''


#创建拥有几个占位符的字符串
def create_args_string(num):
    L = []
    for n in range(num):
        L.append('?')
    return ', '.join(L)

# 定义Field和各种Field子类：
# 该类是为了保存数据库列名和类型的基类
class Field(object):

    def __init__(self, name, column_type, primary_key, default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default

    def __str__(self):
        return '<%s, %s:%s>' % (self.__class__.__name__, self.column_type, self.name)

# 一下几种是具体的列名的数据类型
class StringField(Field):

    def __init__(self, name=None, primary_key=False, default=None,ddl='varchar(100)'):
        super().__init__(name, ddl, primary_key, default)

class BooleanField(Field):

    def __init__(self, name=None, default=False):
        super().__init__(name, 'boolean', False, default)

class IntegerField(Field):

    def __init__(self, name=None, primary_key=False, default=0):
        super().__init__(name, 'bigint', primary_key, default)

class FloatField(Field):

    def __init__(self, name=None, primary_key=False, default=0.0):
        super().__init__(name, 'real', primary_key, default)

class TextField(Field):

    def __init__(self, name=None, default=None):
        super().__init__(name, 'text', False, default)
        

# 通过metaclass：ModelMetaclass 将具体的子类如User的映射信息读取出来
# 元类
class ModelMetaclass(type):
      

    def __new__(cls, name, bases, attrs):
        # 排除Model类本身;如果是基类对象,不做处理,因为没有字段名,没什么可处理的
        if name == 'Model':
            return type.__new__(cls, name, bases,attrs)
        # 获取table名称;保存表名,如果获取不到,则把类名当做表名,完美利用了or短路原理
        tableName = attrs.get('__table__',None) or name
        logging.info('found model: %s (table: %s)' % (name, tableName))
        # 获取所有的Field和主键名;保存列类型的对象
        mappings = dict()
        # 保存列名的数组
        fields = []
        # 主键
        primaryKey = None
        for k,v in attrs.items():
            #是列名的就保存下来
            if isinstance(v, Field):
                logging.info(' found mapping: %s ==> %s' % (k, v))
                mappings[k] = v
                if v.primary_key:
                    # 找到主键
                    if primaryKey:
                        raise RuntimeError('Duplicate primary key for field: %s' % k)
                    primaryKey = k
                else:
                    # 保存非主键的列名
                    fields.append(k)
        if not primaryKey:
            raise RuntimeError('Primary key not found.')
        for k in mappings.keys():
            attrs.pop(k)
        escaped_fields = list(map(lambda f: '`%s`' %f, fields))
        attrs['__mappings__'] = mappings # 保存属性和列的映射关系
        attrs['__table__'] = tableName
        attrs['__primary_key__'] = primaryKey # 主键属性名
        attrs['__fields__'] = fields # 除主键外的属性名
        # 构造默认的SELECT，INSERT，UPDATE和DELETE语句：
        attrs['__select__'] = 'select `%s`, %s from `%s`' %(primaryKey, ','.join(escaped_fields), tableName)
        attrs['__insert__'] = 'insert into `%s` (%s, `%s`) values (%s)' % (tableName, ','.join(escaped_fields), primaryKey, create_args_string(len(escaped_fields) + 1))
        attrs['__update__'] = 'update `%s` set %s where `%s`=?' % (tableName, ','.join(map(lambda f: '`%s`=?' % (mappings.get(f).name or f),fields)),primaryKey)
        attrs['__delete__'] = 'delete from `%s` where `%s`=?' % (tableName,primaryKey)
        return type.__new__(cls, name, bases, attrs)

        '''
        这样，任何继承自Model的类（比如User），会自动通过ModelMetaclass扫描映射关系，并存储到自身的类属性如__table__、__mappings__中。
        '''

# 定义Model 首先要定义的是所有ORM映射的基类Model：
# 这是模型的基类,继承于dict,主要作用就是如果通过点语法来访问对象的属性获取不到的话,可以定制__getattr__来通过key来再次获取字典里的值
class Model(dict, metaclass=ModelMetaclass):

    def __init__(self, **kw):
        super(Model, self).__init__(**kw)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Model' object has no attrbutr '%s'" % key)        # raise语句允许程序员强行产生指定的例外

    def __setattr__(self, key, value):
        self[key] = value

    def getValue(self, key):
        # 调用getattr获取一个未存在的属性,也会走__getattr__方法,但是因为指定了默认返回的值,__getattr__里面的错误永远不会抛出
        return getattr(self, key, None)

    # 使用默认值
    def getValueOrDefault(self, key):
        value = getattr(self, key, None)
        if value is None:
            field = self.__mappings__[key]
            if field.default is not None:
                value = field.default() if callable(field.default) else field.default
                logging.debug('using default values for %s: %s' % (key, str(value)))
                setattr(self, key, value)
        return value
    
    #新的语法  @classmethod装饰器用于把类里面定义的方法声明为该类的类方法
    @classmethod
    #获取表里符合条件的所有数据,类方法的第一个参数为该类名
    async def findAll(cls, where=None, args=None, **kw):
        ' find objects by where clause. '
        sql = [cls.__select__]
        if where:
            sql.append('where')
            sql.append(where)
        if args is None:
            args = []
        orderBy = kw.get('orderBy', None)
        if orderBy:
            sql.append('order by')
            sql.append(orderBy)
        limit = kw.get('limit', None)
        if limit is not None:
            sql.append('limit')
            if isinstance(limit, int):
                sql.append('?')
                args.append(limit)
            elif isinstance(limit, tuple) and len(limit) == 2:
                sql.append('?, ?')
                args.extend(limit)
            else:
                raise ValueError('Invalid limit value: %s' % str(limit))
        rs = await select(' '.join(sql), args)
        return [cls(**r) for r in rs]

    # 该方法不了解
    @classmethod
    async def findNumber(cls, selectField, where=None, args=None):
        ' find number by select and where. '
        sql = ['select %s _num_ from `%s`' % (selectField, cls.__table__)]
        if where:
            sql.append('where')
            sql.append(where)
        rs = await select(' '.join(sql), args, 1)
        if len(rs) == 0:
            return None
        return rs[0]['_num_']

    # 主键查找的方法
    @classmethod
    async def find(cls, pk):
        ' find object by primary key. '
        rs = await select('%s where `%s`=?' % (cls.__select__, cls.__primary_key__), [pk], 1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])


    # 以下的都是对象方法,所以可以不用传任何参数,方法内部可以使用该对象的所有属性,及其方便
    # 保存实例到数据库
    async def save(self):
        args = list(map(self.getValueOrDefault, self.__fields__))
        args.append(self.getValueOrDefault(self.__primary_key__))
        rows = await execute(self.__insert__, args)
        if rows != 1:
            logging.warn('failed to insert record: affected rows: %s' % rows)

    # 更新数据库数据
    async def update(self):
        args = list(map(self.getValue, self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        rows = await execute(self.__update__, args)
        if rows != 1:
            logging.warn('failed to update by primary key: affected rows: %s' % rows)

    # 删除数据
    async def remove(self):
        args = [self.getValue(self.__primary_key__)]
        rows = await execute(self.__delete__, args)
        if rows != 1:
            logging.warn('failed to remove by primary key: affected rows: %s' % rows)

            
async def close_pool():
    logging.info('close database connection pool...')
    global __pool
    if __pool is not None:
        __pool.close()
        await __pool.wait_closed()



'''
# 然后，我们往Model类添加class方法，就可以让所有子类调用class方法：

class Model(dict):

    ...

    @classmethod
    @asyncio.coroutine
    def find(cls, pk):
        'find object by primary key.'
        rs = yield from select('%s where `%s`=?' % (cls.__select__, cls.__primary_key__),[pk],1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])
 # 往Model类添加实例方法，就可以让所有子类调用实例方法：
class Model(dict):


     ...

     @asyncio.coroutine
     def save(self):
         args = list(map(self.getValueOrDefault, self.__fields__))
         args.append(self.getValueOrDefault(self.__primary_key__))
         rows = yield from execute(self.__insert__, args)
         if rows !=1:
             logging.warn('failed to insert record: affected rows: %s' % rows)


'''

'''
#以下为测试
loop = asyncio.get_event_loop()
loop.run_until_complete(create_pool(host='127.0.0.1', port=3306,user='root', password='xL889530',db='web', loop=loop))
rs = loop.run_until_complete(select('select * from demo',None))
#获取到了数据库返回的数据
print("heh:%s" % rs)
'''
