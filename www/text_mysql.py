import orm
from models import User, Blog, Comment
import asyncio
import sys


async def test(loop):
    # 创建连接池
    db_dict = {'user': 'root', 'password': 'xL889530', 'db': 'awesome'}
    await orm.create_pool(loop=loop, **db_dict)
    #u = User(name='Test', emai='test@example.com', passwd='12345', image='about:blank', id='123')
    u = User()
    '''
    u.name = '123'
    
    u.email = '1234@qq.com'
    u.passwd = '56789'
    u.image = 'yasuo'
    u.id = '12'
    '''
    u.id = '123'
    await u.remove()
    await orm.close_pool()

loop = asyncio.get_event_loop()
loop.run_until_complete(test(loop))
loop.close()
