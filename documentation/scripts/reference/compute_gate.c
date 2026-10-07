#define _GNU_SOURCE
#include <link.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include <sched.h>

extern unsigned long compat_strtoul(const char *, char **, int);
__asm__(".symver compat_strtoul,strtoul@GLIBC_2.2.5");
struct gate { uint32_t done,go,seen[64]; uint64_t return_offset[64]; };
static struct gate *gate;
static uintptr_t main_base;
static unsigned worker,expected,calls;
static int native_test;
static volatile unsigned char *m5_base;
static void (*original)(void *,void *);
static const unsigned char prefix[14]={0x41,0x55,0x41,0x54,0x45,0x31,0xe4,0x55,0x53,0x31,0xed,0x48,0x89,0xfb};
static void die(const char *s) { (void)write(2,s,strlen(s)); _exit(97); }
static int find_main(struct dl_phdr_info *p,size_t n,void *arg) {
    (void)n;(void)arg;
    if(!p->dlpi_name || !p->dlpi_name[0]) {main_base=p->dlpi_addr;return 1;} return 0;
}
static void jump(unsigned char *dst,uintptr_t target) {
    const unsigned char insn[6]={0xff,0x25,0,0,0,0};
    memcpy(dst,insn,6);memcpy(dst+6,&target,8);
}
static void marker(unsigned op) {
    register uint64_t id __asm__("rdi")=0x434f4d50;
    register uint64_t tid __asm__("rsi")=worker;
    __asm__ volatile("movq (%2), %%rax" : "+D"(id),"+S"(tid) : "r"(m5_base+(op<<8)) : "rax","memory");
}
static void log_call(const char *phase,unsigned call,uintptr_t offset) {
    struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);
    fprintf(stderr,"COMPUTE_%s worker=%u call=%u return_offset=%#lx time=%ld.%09ld\n",phase,worker,call,(unsigned long)offset,t.tv_sec,t.tv_nsec);
}
__attribute__((noinline)) static void compute(void *list,void *patches) {
    uintptr_t offset=(uintptr_t)__builtin_return_address(0)-main_base;
    unsigned call=++calls;
    log_call("ENTER",call,offset);
    if(call==7) {
        /* First mode of iteration 1, after all six modes of iteration 0. */
        if(offset!=0x1625)die("COMPUTE_GATE unexpected selected call site\n");
        if(__atomic_exchange_n(&gate->seen[worker],1,__ATOMIC_SEQ_CST))die("COMPUTE_GATE duplicate arrival\n");
        gate->return_offset[worker]=offset;
        unsigned done=__atomic_add_fetch(&gate->done,1,__ATOMIC_SEQ_CST);
        if(done==expected) {
            if(!native_test)marker(0x5a);
            __atomic_store_n(&gate->go,1,__ATOMIC_SEQ_CST);
        } else while(!__atomic_load_n(&gate->go,__ATOMIC_SEQ_CST))sched_yield();
        log_call("SELECTED",call,offset);
    }
    original(list,patches);
    log_call("EXIT",call,offset);
    /* Every core guards the end of the selected computation. */
    if(call==7 && !native_test)marker(0x5b);
}
__attribute__((constructor)) static void setup(void) {
    const char *path=getenv("NAMD_GATE_FILE"),*count=getenv("NAMD_GATE_EXPECTED"),*id=getenv("NAMD_GATE_WORKER");
    if(!path||!count||!id)die("COMPUTE_GATE missing configuration\n");
    expected=compat_strtoul(count,0,10);worker=compat_strtoul(id,0,10);
    if(expected<1||expected>64||worker>=expected)die("COMPUTE_GATE invalid worker count\n");
    int fd=open(path,O_RDWR);if(fd<0)die("COMPUTE_GATE cannot open gate\n");
    gate=mmap(0,4096,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);close(fd);
    if(gate==MAP_FAILED)die("COMPUTE_GATE gate mmap failed\n");
    native_test=getenv("NAMD_GATE_NATIVE_TEST")!=0;
    if(!native_test) {
        fd=open("/dev/mem",O_RDWR|O_SYNC);if(fd<0)die("COMPUTE_GATE cannot open /dev/mem\n");
        m5_base=mmap(0,65536,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0xffff0000ULL);close(fd);
        if(m5_base==MAP_FAILED)die("COMPUTE_GATE MMIO mmap failed\n");
    }
    if(!dl_iterate_phdr(find_main,0))die("COMPUTE_GATE missing executable base\n");
    unsigned char *entry=(unsigned char *)(main_base+0x3830);
    if(memcmp(entry,prefix,sizeof(prefix))) {
        fprintf(stderr,"COMPUTE_GATE base=%#lx observed=",(unsigned long)main_base);
        for(unsigned i=0;i<14;i++)fprintf(stderr,"%02x",entry[i]);
        fprintf(stderr,"\n");
        die("COMPUTE_GATE unsupported executable prologue\n");
    }
    /* The stolen prefix consists solely of complete, position-independent
       instructions. No stack, RIP-relative addressing or branches relocate. */
    unsigned char *trampoline=mmap(0,4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    if(trampoline==MAP_FAILED)die("COMPUTE_GATE trampoline mmap failed\n");
    memcpy(trampoline,prefix,14);jump(trampoline+14,(uintptr_t)(entry+14));
    if(mprotect(trampoline,4096,PROT_READ|PROT_EXEC))die("COMPUTE_GATE trampoline mprotect failed\n");
    original=(void (*)(void *,void *))trampoline;
    void *page=(void *)((uintptr_t)entry & ~(uintptr_t)4095);
    if(mprotect(page,4096,PROT_READ|PROT_WRITE|PROT_EXEC))die("COMPUTE_GATE text mprotect failed\n");
    jump(entry,(uintptr_t)compute);
    if(mprotect(page,4096,PROT_READ|PROT_EXEC))die("COMPUTE_GATE text restore failed\n");
}
