"""Convenience entry point for development.

Run with `uv run python main.py` to start the Django development server
(the same as `python manage.py runserver`).
"""
import subprocess
import sys


def main():
    sys.exit(subprocess.call([sys.executable, 'manage.py', 'runserver', *sys.argv[1:]]))


if __name__ == '__main__':
    main()