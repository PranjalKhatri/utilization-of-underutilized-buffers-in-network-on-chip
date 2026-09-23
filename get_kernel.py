# get_kernel.py
from gem5.resources.resource import obtain_resource
kernel = obtain_resource("x86-linux-kernel-5.4.49")
print("\n--- YOUR KERNEL PATH IS ---")
print(kernel.get_local_path())
print("---------------------------\n")