import paramiko
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('10.<REDACTED-RPI-IP>', username='cortex', password='REDACTED-RPI-PASSWORD', timeout=10, look_for_keys=False, allow_agent=False)
cmds = [
    'echo === __main__ file_only block ===',
    'grep -n -A8 "_full_mode" ~/ProjectCortex/rpi5/__main__.py',
    'echo === log_setup def setup_logging ===',
    'grep -n "def setup_logging" ~/ProjectCortex/rpi5/cli/log_setup.py',
    'echo === ls logs/ ===',
    'ls -la ~/ProjectCortex/logs/ 2>/dev/null',
    'echo === wc cortex.log ===',
    'wc -lc ~/ProjectCortex/logs/cortex.log 2>/dev/null',
    'echo === cat cortex.log first 5 ===',
    'head -5 ~/ProjectCortex/logs/cortex.log 2>/dev/null',
]
out = ''
for cmd in cmds:
    si, so, se = c.exec_command(cmd, timeout=10)
    out += so.read().decode('utf-8', errors='replace')
    out += se.read().decode('utf-8', errors='replace')
print(out)
c.close()
