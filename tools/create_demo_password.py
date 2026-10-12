"""交互读取演示口令，仅输出哈希供托管Secrets使用；不保存明文。"""
from getpass import getpass

from frontend.share_access import hash_access_password


def main():
    print('设置演示访问口令，至少12个字符。输入时不回显。')
    password = getpass('口令：')
    confirmation = getpass('再次输入：')
    if password != confirmation:
        raise SystemExit('两次口令不一致，未生成配置。')
    hashed = hash_access_password(password)
    print('\n将下面两行复制到Streamlit的Secrets配置（不要写入GitHub）：')
    print('[public_demo]')
    print(f'password_hash = "{hashed}"')


if __name__ == '__main__':
    main()
