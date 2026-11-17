import time, subprocess
t=time.time()
subprocess.run(['sleep','5'])
print('elapsed', round(time.time()-t,2))
