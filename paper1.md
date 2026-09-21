scons setconfig build/X86 RUBY_PROTOCOL_MOESI_CMP_DIRECTORY=y
scons build/X86/gem5.opt -j$(nproc)

scons setconfig build/X86 RUBY_PROTOCOL_MOESI_CMP_directory=y
grep -i "MOESI_CMP_directory\|MESI_Two_Level" build/X86/gem5.build/config