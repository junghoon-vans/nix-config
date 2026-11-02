#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

static const int forwarded_signals[] = {
    SIGTERM, SIGINT, SIGHUP, SIGUSR1, SIGUSR2,
};

static void report_error(const char *operation, int error) {
  fprintf(stderr, "hermes-gateway-host: %s: %s\n", operation,
          strerror(error));
}

static void sigchld_handler(int signal_number) {
  (void)signal_number;
}

static int set_default_dispositions(const sigset_t *signals) {
  struct sigaction action;
  memset(&action, 0, sizeof(action));
  action.sa_handler = SIG_DFL;
  if (sigemptyset(&action.sa_mask) != 0) {
    return errno;
  }

  for (size_t i = 0; i < sizeof(forwarded_signals) / sizeof(forwarded_signals[0]);
       ++i) {
    if (sigismember(signals, forwarded_signals[i]) == 1 &&
        sigaction(forwarded_signals[i], &action, NULL) != 0) {
      return errno;
    }
  }
  if (sigismember(signals, SIGCHLD) == 1) {
    /* Darwin discards SIGCHLD with SIG_DFL, so sigwait cannot receive it. */
    action.sa_handler = sigchld_handler;
    if (sigaction(SIGCHLD, &action, NULL) != 0) {
      return errno;
    }
  }
  return 0;
}

static int prepare_signal_masks(sigset_t *wait_set, sigset_t *child_mask) {
  sigset_t blocked_set;
  if (sigemptyset(&blocked_set) != 0 || sigemptyset(wait_set) != 0) {
    return errno;
  }

  for (size_t i = 0; i < sizeof(forwarded_signals) / sizeof(forwarded_signals[0]);
       ++i) {
    if (sigaddset(&blocked_set, forwarded_signals[i]) != 0 ||
        sigaddset(wait_set, forwarded_signals[i]) != 0) {
      return errno;
    }
  }
  if (sigaddset(&blocked_set, SIGCHLD) != 0 ||
      sigaddset(wait_set, SIGCHLD) != 0) {
    return errno;
  }

  int error = set_default_dispositions(&blocked_set);
  if (error != 0) {
    return error;
  }

  sigset_t original_mask;
  if (sigprocmask(SIG_BLOCK, &blocked_set, &original_mask) != 0) {
    return errno;
  }

  *child_mask = original_mask;
  for (size_t i = 0; i < sizeof(forwarded_signals) / sizeof(forwarded_signals[0]);
       ++i) {
    if (sigdelset(child_mask, forwarded_signals[i]) != 0) {
      return errno;
    }
  }
  return 0;
}

static int spawn_gateway(char **gateway_argv, const sigset_t *wait_set,
                         const sigset_t *child_mask, pid_t *child_pid) {
  posix_spawnattr_t attributes;
  int error = posix_spawnattr_init(&attributes);
  if (error != 0) {
    return error;
  }

  short flags = POSIX_SPAWN_SETPGROUP | POSIX_SPAWN_SETSIGMASK |
                POSIX_SPAWN_SETSIGDEF;
  error = posix_spawnattr_setflags(&attributes, flags);
  if (error == 0) {
    error = posix_spawnattr_setpgroup(&attributes, 0);
  }
  if (error == 0) {
    error = posix_spawnattr_setsigmask(&attributes, child_mask);
  }
  if (error == 0) {
    error = posix_spawnattr_setsigdefault(&attributes, wait_set);
  }
  if (error == 0) {
    error = posix_spawn(child_pid, gateway_argv[0], NULL, &attributes,
                        gateway_argv, environ);
  }

  (void)posix_spawnattr_destroy(&attributes);
  return error;
}

static int wait_for_gateway(pid_t child_pid, const sigset_t *wait_set,
                            int *child_status) {
  for (;;) {
    pid_t result = waitpid(child_pid, child_status, WNOHANG);
    if (result == child_pid) {
      return 0;
    }
    if (result == -1 && errno != EINTR) {
      return errno;
    }

    int received_signal = 0;
    int error = sigwait(wait_set, &received_signal);
    if (error != 0) {
      /* If waiting for signals fails, still stop the child before waiting. */
      (void)kill(-child_pid, SIGTERM);
      do {
        result = waitpid(child_pid, child_status, 0);
      } while (result == -1 && errno == EINTR);
      return result == child_pid ? 0 : errno;
    }
    if (received_signal == SIGCHLD) {
      continue;
    }

    /* Hermes uses USR1/USR2 as direct-child control/diagnostic signals. */
    pid_t target = (received_signal == SIGUSR1 || received_signal == SIGUSR2)
                      ? child_pid
                      : -child_pid;
    if (kill(target, received_signal) != 0 && errno != ESRCH) {
      report_error("forwarding signal", errno);
    }
  }
}

static int gateway_exit_code(int status) {
  if (WIFEXITED(status)) {
    int exit_code = WEXITSTATUS(status);
    /* Hermes 78 means the configuration is invalid; do not KeepAlive-restart. */
    return exit_code == 78 ? 0 : exit_code;
  }
  if (WIFSIGNALED(status)) {
    return 128 + WTERMSIG(status);
  }
  return 1;
}

int main(int argc, char **argv) {
  if (argc < 2) {
    fprintf(stderr, "Usage: %s HERMES_EXECUTABLE [ARG ...]\n", argv[0]);
    return 64;
  }

  sigset_t wait_set;
  sigset_t child_mask;
  int error = prepare_signal_masks(&wait_set, &child_mask);
  if (error != 0) {
    report_error("preparing signal handling", error);
    return 126;
  }

  pid_t child_pid;
  error = spawn_gateway(&argv[1], &wait_set, &child_mask, &child_pid);
  if (error != 0) {
    report_error("starting Hermes", error);
    return error == ENOENT ? 127 : 126;
  }

  int child_status = 0;
  error = wait_for_gateway(child_pid, &wait_set, &child_status);
  if (error != 0) {
    report_error("waiting for Hermes", error);
    return 1;
  }
  return gateway_exit_code(child_status);
}
