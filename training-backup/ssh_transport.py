"""Rsync transport through the existing credential-isolated field SSH helper."""
import os,shlex,sys
os.execv('/usr/bin/python3',['/usr/bin/python3','/Users/ufo-files-agent/field-migration/training-ssh.py',shlex.join(sys.argv[2:])])
