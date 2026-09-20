"""Print one new key; never import configuration or persist it."""
from app.security.mfa_crypto import generate_key


def main():
    print(generate_key())


if __name__ == '__main__':
    main()
