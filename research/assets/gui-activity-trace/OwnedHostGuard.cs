// E007 v1, runtime-compiled only inside private TEMP after the PID challenge.
// The owner separately proves exact Job membership using the retained launch handle.
// No job handle is transferred: it must not outlive the owning controller.
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class OwnedHostGuard
{
    [DllImport("kernel32.dll")] static extern uint GetCurrentProcessId();
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool GetProcessTimes(IntPtr process, out long birth, out long exit, out long kernel, out long user);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool IsProcessInJob(IntPtr process, IntPtr job, out bool member);

    public static long Birth()
    {
        long birth, exit, kernel, user;
        if (!GetProcessTimes(GetCurrentProcess(), out birth, out exit, out kernel, out user))
            throw new Win32Exception();
        return birth;
    }

    public static bool Confirm(uint expectedPid, long expectedBirth)
    {
        // Reject relayed script execution before touching any supplied handle.
        if (GetCurrentProcessId() != expectedPid || Birth() != expectedBirth)
            throw new InvalidOperationException("Fresh launched PID/creation identity mismatch");
        bool member;
        if (!IsProcessInJob(GetCurrentProcess(), IntPtr.Zero, out member)) throw new Win32Exception();
        if (!member) throw new InvalidOperationException("Host is not in any Job");
        return true; // exact membership/flags are independently re-read by owner
    }
}
