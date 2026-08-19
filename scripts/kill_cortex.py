import paramiko
import os
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.127.61.31', username='cortex', password=os.environ['RPI_PASSWORD'], timeout=10)
def run(cmd, timeout=10):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return stdout.read().decode(errors='replace')

out = run('pkill -9 -f "python.*rpi5" 2>/dev/null; sleep 1; ps aux | grep "python.*rpi5" | grep -v grep | wc -l', timeout=15)
print(f'Remaining cortex processes: {out.strip()}')
ssh.close()