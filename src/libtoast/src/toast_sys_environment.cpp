
// Copyright (c) 2015-2019 by the parties listed in the AUTHORS file.
// All rights reserved.  Use of this source code is governed by
// a BSD-style license that can be found in the LICENSE file.

#include <toast/sys_environment.hpp>

#include <cstring>

extern "C" {
#include <signal.h>
}

#ifdef _OPENMP
# include <omp.h>
#endif // ifdef _OPENMP

// These are not in the original POSIX.1-1990 standard so we are defining
// them in case the OS hasn't.
// POSIX-1.2001
#ifndef SIGTRAP
# define SIGTRAP 5
#endif // ifndef SIGTRAP

// Not specified in POSIX.1-2001, but nevertheless appears on most other
// UNIX systems, where its default action is typically to terminate the
// process with a core dump.
#ifndef SIGEMT
# define SIGEMT 7
#endif // ifndef SIGEMT

// POSIX-1.2001
#ifndef SIGURG
# define SIGURG 16
#endif // ifndef SIGURG

// POSIX-1.2001
#ifndef SIGXCPU
# define SIGXCPU 24
#endif // ifndef SIGXCPU

// POSIX-1.2001
#ifndef SIGXFSZ
# define SIGXFSZ 25
#endif // ifndef SIGXFSZ

// POSIX-1.2001
#ifndef SIGVTALRM
# define SIGVTALRM 26
#endif // ifndef SIGVTALRM

// POSIX-1.2001
#ifndef SIGPROF
# define SIGPROF 27
#endif // ifndef SIGPROF

// POSIX-1.2001
#ifndef SIGINFO
# define SIGINFO 29
#endif // ifndef SIGINFO


toast::Environment::Environment() {
    // Check debug log-level
    char * envval = ::getenv("TOAST_LOGLEVEL");

    if (envval == NULL) {
        loglvl_ = std::string("INFO");
    } else {
        loglvl_ = std::string(envval);
    }

    // Enable signals if desired
    signals_avail_.clear();
    signals_avail_.push_back("SIGHUP");
    signals_value_["SIGHUP"] = SIGHUP;
    signals_avail_.push_back("SIGINT");
    signals_value_["SIGINT"] = SIGINT;
    signals_avail_.push_back("SIGQUIT");
    signals_value_["SIGQUIT"] = SIGQUIT;
    signals_avail_.push_back("SIGILL");
    signals_value_["SIGILL"] = SIGILL;
    signals_avail_.push_back("SIGTRAP");
    signals_value_["SIGTRAP"] = SIGTRAP;
    signals_avail_.push_back("SIGABRT");
    signals_value_["SIGABRT"] = SIGABRT;
    signals_avail_.push_back("SIGEMT");
    signals_value_["SIGEMT"] = SIGEMT;
    signals_avail_.push_back("SIGFPE");
    signals_value_["SIGFPE"] = SIGFPE;

    // Should never try to trap SIGKILL...
    // signals_avail_.push_back("SIGKILL");
    signals_avail_.push_back("SIGBUS");
    signals_value_["SIGBUS"] = SIGBUS;
    signals_avail_.push_back("SIGSEGV");
    signals_value_["SIGSEGV"] = SIGSEGV;
    signals_avail_.push_back("SIGSYS");
    signals_value_["SIGSYS"] = SIGSYS;
    signals_avail_.push_back("SIGPIPE");
    signals_value_["SIGPIPE"] = SIGPIPE;
    signals_avail_.push_back("SIGALRM");
    signals_value_["SIGALRM"] = SIGALRM;
    signals_avail_.push_back("SIGTERM");
    signals_value_["SIGTERM"] = SIGTERM;
    signals_avail_.push_back("SIGURG");
    signals_value_["SIGURG"] = SIGURG;
    signals_avail_.push_back("SIGTSTP");
    signals_value_["SIGTSTP"] = SIGTSTP;
    signals_avail_.push_back("SIGXCPU");
    signals_value_["SIGXCPU"] = SIGXCPU;
    signals_avail_.push_back("SIGXFSZ");
    signals_value_["SIGXFSZ"] = SIGXFSZ;
    signals_avail_.push_back("SIGVTALRM");
    signals_value_["SIGVTALRM"] = SIGVTALRM;
    signals_avail_.push_back("SIGPIPE");
    signals_value_["SIGPIPE"] = SIGPIPE;

    signals_enabled_.clear();
    for (auto const & sig : signals_avail_) {
        signals_enabled_[sig] = false;
    }

    envval = ::getenv("TOAST_SIGNALS");
    if (envval != NULL) {
        if (strncmp(envval, "ALL", 3) == 0) {
            // Enable everything
            for (auto const & sig : signals_avail_) {
                signals_enabled_[sig] = true;
            }
        } else {
            // Split comma-separated list of signals to enable
        }
    }

    // OpenMP
    max_threads_ = 1;
    #ifdef _OPENMP
    max_threads_ = omp_get_max_threads();
    #endif // ifdef _OPENMP

    // Was toast configured to use MPI?  We put this setting here in the
    // non-MPI library so that we can always access it before trying load
    // the MPI library.
    use_mpi_ = true;

    have_mpi_ = false;
    #ifdef HAVE_MPI

    // Build system found MPI
    have_mpi_ = true;
    #endif // ifdef HAVE_MPI

    // See if the user explicitly disabled MPI in the runtime environment.
    bool disabled_mpi_ = false;
    envval = ::getenv("TOAST_MPI_DISABLE");
    if (envval != NULL) {
        disabled_mpi_ = true;
    }

    // Handle special case of running on a NERSC login node, where MPI is
    // used for compilation, but cannot be used at runtime.
    envval = ::getenv("NERSC_HOST");
    if (envval == NULL) {
        at_nersc_ = false;
    } else {
        at_nersc_ = true;
    }
    envval = ::getenv("SLURM_JOB_NAME");
    if (envval == NULL) {
        in_slurm_ = false;
    } else {
        in_slurm_ = true;
    }

    if (!have_mpi_) {
        use_mpi_ = false;
    }
    if (disabled_mpi_) {
        use_mpi_ = false;
    }
    if (at_nersc_ && !in_slurm_) {
        // we are on a login node...
        use_mpi_ = false;
    }
}

toast::Environment & toast::Environment::get() {
    static toast::Environment instance;

    return instance;
}

std::string toast::Environment::log_level() const {
    return loglvl_;
}

void toast::Environment::set_log_level(char const * level) {
    loglvl_ = std::string(level);
}

bool toast::Environment::use_mpi() const {
    return use_mpi_;
}

int toast::Environment::max_threads() const {
    return max_threads_;
}

std::vector <std::string> toast::Environment::signals() const {
    return signals_avail_;
}

void toast::Environment::print() const {
    std::string prefix("TOAST ENV");

    fprintf(stdout, "%s: Logging level = %s\n", prefix.c_str(),
            loglvl_.c_str());

    fprintf(stdout, "%s: Signal handling status:\n", prefix.c_str());

    for (auto const & sig : signals_avail_) {
        if (signals_enabled_.count(sig) == 0) {
            fprintf(stdout, "%s:   %9s unavailable\n", prefix.c_str(),
                    sig.c_str());
        } else {
            if (signals_enabled_.at(sig)) {
                fprintf(stdout, "%s:   %9s enabled\n", prefix.c_str(),
                        sig.c_str());
            } else {
                fprintf(stdout, "%s:   %9s disabled\n", prefix.c_str(),
                        sig.c_str());
            }
        }
    }
    fprintf(stdout, "%s: Max threads = %d\n", prefix.c_str(),
            max_threads_);
    if (have_mpi_) {
        fprintf(stdout, "%s: MPI build enabled\n", prefix.c_str());
    } else {
        fprintf(stdout, "%s: MPI build disabled\n", prefix.c_str());
    }
    if (use_mpi_) {
        fprintf(stdout, "%s: MPI runtime enabled\n", prefix.c_str());
    } else {
        fprintf(stdout, "%s: MPI runtime disabled\n", prefix.c_str());
        if (at_nersc_ && !in_slurm_) {
            fprintf(stdout, "%s:   Cannot use MPI on NERSC login nodes\n",
                    prefix.c_str());
        }
    }
    fflush(stdout);
    return;
}
