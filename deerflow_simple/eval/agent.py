# 测试agent
# pyright: reportImplicitRelativeImport=false

import json

from deerflow_simple.config import SimpleConfig
from deerflow_simple.model import create_chat_model

prompt = """

"""

model = create_chat_model(SimpleConfig.from_env(), temperature=0.5)


def chat(msg: str) -> str:
    
    message: list[dict[str, str]] = [
        {'role': 'system', 'content': prompt},
        {'role': 'user', 'content': msg}
    ]
    s: str = ''

    try:
        rsp = model.invoke(message)
        s = rsp.content
        
    except ValueError as e:
        print(f'配置错误：{e}')
    except ConnectionError as e:
        print(f'网络连接错误：{e}')
    except Exception as e:
        print(f'异常：{e}')

    return s


if __name__ == '__main__':
    s: str = chat(msg='你好')
    print(s)







