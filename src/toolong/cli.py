from __future__ import annotations

from importlib.metadata import version
import os
import sys

import click

from toolong.ui import UI


@click.command()
@click.version_option(version("toolong"))
@click.argument("files", metavar="FILE1 FILE2", nargs=-1)
@click.option("-m", "--merge", is_flag=True, help="Merge files.")
@click.option(
    "-o",
    "--output-merge",
    metavar="PATH",
    nargs=1,
    help="Path to save merged file (requires -m).",
)
def run(files: list[str], merge: bool, output_merge: str) -> None:
    """View / tail / search log files."""
    stdin_tty = sys.__stdin__.isatty()
    if not files and stdin_tty:
        ctx = click.get_current_context()
        click.echo(ctx.get_help())
        ctx.exit()
    if stdin_tty:
        try:
            ui = UI(files, merge=merge, save_merge=output_merge)
            ui.run()
        except Exception:
            pass
    else:
        import signal
        import selectors
        import subprocess
        import tempfile
        import termios  # For flushing terminal input

        child_process = None

        def disable_mouse_tracking():
            # Disable X10 mouse mode, normal mouse tracking, and SGR extended mode
            sys.stdout.write("\x1b[?9l")
            sys.stdout.write("\x1b[?1000l")
            sys.stdout.write("\x1b[?1006l")
            sys.stdout.flush()

        def restore_terminal_cursor():
            # Reenable the terminal cursor with the proper escape sequence
            sys.stdout.write("\x1b[?25h")
            sys.stdout.flush()

        def request_exit(*args) -> None:
            disable_mouse_tracking()
            restore_terminal_cursor()
            sys.stderr.write("^C\n")
            nonlocal child_process
            if child_process is not None:
                child_process.terminate()
                child_process.wait()
            sys.exit(0)

        signal.signal(signal.SIGINT, request_exit)
        signal.signal(signal.SIGTERM, request_exit)

        # Write piped data to a temporary file
        with tempfile.NamedTemporaryFile(mode="w+b", buffering=0, prefix="tl_") as temp_file:
            try:
                tty_stdin = open("/dev/tty", "rb", buffering=0)
            except OSError:
                tty_stdin = open(os.devnull, "rb", buffering=0)
            with tty_stdin:
                with subprocess.Popen(
                    [sys.argv[0], temp_file.name],
                    stdin=tty_stdin,
                    close_fds=True,
                    env={**os.environ, "TEXTUAL_ALLOW_SIGNALS": "1"},
                ) as process:
                    child_process = process
                    selector = selectors.SelectSelector()
                    selector.register(sys.stdin.fileno(), selectors.EVENT_READ)

                    try:
                        while process.poll() is None:
                            for _, event in selector.select(0.1):
                                if process.poll() is not None:
                                    break
                                if event & selectors.EVENT_READ:
                                    line = os.read(sys.stdin.fileno(), 1024 * 64)
                                    if line:
                                        temp_file.write(line)
                                    else:
                                        break
                    finally:
                        selector.unregister(sys.stdin.fileno())
                        selector.close()
                        # Flush any pending input from the terminal, if possible
                        try:
                            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
                        except Exception:
                            pass
                        sys.stdin.close()
