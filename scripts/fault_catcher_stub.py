"""The bridge's access-violation catcher (lua/parley_bridge.lua M.FAULT_STUB), as x86 machine code.

A vectored exception handler: on every error-class exception (code 0xC...) it writes into BUF (the
0x11223344 marker, patched by the bridge to its file mapping) the count so far (+0), the address (+4), the
stack words copied (+8), the code (+0xC), the CONTEXT (+0x10, 204 bytes) and up to 4 KB of the faulting thread's stack
(+0xDC), only when StackLimit (fs:[8]) <= esp < StackBase (fs:[4]), unsigned, so the copy never leaves the
committed stack. It always
returns EXCEPTION_CONTINUE_SEARCH: the game's own handlers run as before.

`python scripts/fault_catcher_stub.py` prints the bytes for the Lua table; a test checks the two agree.
Check the encoding with: objdump -D -b binary -m i386 <file of these bytes>
"""


def stub() -> bytes:
    b = bytearray()

    def e(*xs: int) -> None:
        b.extend(xs)

    e(0xFC)                                    # cld
    e(0x8B, 0x44, 0x24, 0x04)                  # mov eax,[esp+4]   EXCEPTION_POINTERS*
    e(0x8B, 0x08)                              # mov ecx,[eax]     EXCEPTION_RECORD*
    # every error-class code (0xC...): access violations, c0000417 (a CRT call's invalid parameter, the
    # 11-13 turn 705 crash), c0000409, stack overflow. LuaJIT's errors (e24c4a02), C++ throws (e06d7363)
    # and debug prints (40010006) are not errors and pass untouched
    e(0x8B, 0x11)                              # mov edx,[ecx]     ExceptionCode
    e(0x81, 0xE2, 0x00, 0x00, 0x00, 0xF0)      # and edx,F0000000
    e(0x81, 0xFA, 0x00, 0x00, 0x00, 0xC0)      # cmp edx,C0000000
    j_done = len(b); e(0x75, 0x00)             # jne done
    e(0x56, 0x57)                              # push esi; push edi
    e(0xBA, 0x44, 0x33, 0x22, 0x11)            # mov edx,BUF
    e(0xFF, 0x02)                              # inc dword [edx]   errors so far
    e(0x8B, 0x39)                              # mov edi,[ecx]
    e(0x89, 0x7A, 0x0C)                        # mov [edx+0Ch],edi the code
    e(0x8B, 0x49, 0x0C)                        # mov ecx,[ecx+0Ch] ExceptionAddress
    e(0x89, 0x4A, 0x04)                        # mov [edx+4],ecx
    e(0x8B, 0x70, 0x04)                        # mov esi,[eax+4]   CONTEXT*
    e(0x8D, 0x7A, 0x10)                        # lea edi,[edx+10h]
    e(0xB9, 0x33, 0x00, 0x00, 0x00)            # mov ecx,51        204 bytes of CONTEXT
    e(0xF3, 0xA5)                              # rep movsd
    e(0x8B, 0x70, 0x04)                        # mov esi,[eax+4]
    e(0x8B, 0xB6, 0xC4, 0x00, 0x00, 0x00)      # mov esi,[esi+0C4h] ctx->Esp
    # copy only when StackLimit <= esp < StackBase (unsigned): a corrupted esp would fault in here,
    # crash the game and overwrite the real fault (review 11-13)
    e(0x64, 0x8B, 0x0D, 0x08, 0x00, 0x00, 0x00)  # mov ecx,fs:[8]  the thread's StackLimit
    e(0x39, 0xCE)                              # cmp esi,ecx
    j_none1 = len(b); e(0x72, 0x00)            # jb none           below the committed stack
    e(0x64, 0x8B, 0x0D, 0x04, 0x00, 0x00, 0x00)  # mov ecx,fs:[4]  the thread's StackBase
    e(0x39, 0xCE)                              # cmp esi,ecx
    j_none = len(b); e(0x73, 0x00)             # jae none          at/above the base
    e(0x29, 0xF1)                              # sub ecx,esi       bytes up to the base
    e(0xC1, 0xE9, 0x02)                        # shr ecx,2         words
    e(0x81, 0xF9, 0x00, 0x04, 0x00, 0x00)      # cmp ecx,1024
    j_ok = len(b); e(0x76, 0x00)               # jbe ok
    e(0xB9, 0x00, 0x04, 0x00, 0x00)            # mov ecx,1024
    ok = len(b)
    e(0x89, 0x4A, 0x08)                        # mov [edx+8],ecx   words copied
    e(0x8D, 0xBA, 0xDC, 0x00, 0x00, 0x00)      # lea edi,[edx+0DCh]
    e(0xF3, 0xA5)                              # rep movsd
    j_out = len(b); e(0xEB, 0x00)              # jmp out
    none = len(b)
    e(0xC7, 0x42, 0x08, 0x00, 0x00, 0x00, 0x00)  # mov dword [edx+8],0
    out = len(b)
    e(0x5F, 0x5E)                              # pop edi; pop esi
    done = len(b)
    e(0x31, 0xC0)                              # xor eax,eax       EXCEPTION_CONTINUE_SEARCH
    e(0xC2, 0x04, 0x00)                        # ret 4
    for j, t in ((j_done, done), (j_none1, none), (j_none, none), (j_ok, ok), (j_out, out)):
        b[j + 1] = t - (j + 2)
    return bytes(b)


if __name__ == "__main__":
    print(",".join(str(x) for x in stub()))
