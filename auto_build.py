#!/usr/bin/env python

import argparse
from datetime import datetime
import multiprocessing
import os
import re
import subprocess
import sys
import time

MY_DIR = os.path.dirname(__file__)
VEEWEE_CMD_BASE = ['bundle', 'exec', 'veewee']


def job_gen(args):
    for provider in args.providers:
        for box_name in args.boxes:
            yield (provider, box_name, args.datestamp)
            # Don't hand out jobs too quickly (thundering herd at start)
            time.sleep(50)


def build_box(job_args):
    provider, box_name, datestamp = job_args
    exp_box_path = os.path.join(MY_DIR, '%s.box' % box_name)
    final_box_path = os.path.join(MY_DIR, '%s%s-%s.box' % (
        box_name, '-vmware' if provider == 'fusion' else '', datestamp))

    # We try a destroy first (ignoring failure) in case a VM leaked earlier
    # (--force doesn't seem to be sufficient?).
    halt_cmd = VEEWEE_CMD_BASE + [provider, 'halt', box_name]
    destroy_cmd = VEEWEE_CMD_BASE + [provider, 'destroy', box_name]
    build_cmd = VEEWEE_CMD_BASE + [provider, 'build', box_name, '--auto']
    build_log_path = os.path.join(
        args.log_dir, 'auto_build.%s.%s.%s.build.log' % (
            box_name, provider, datestamp))
    export_log_path = os.path.join(
        args.log_dir, 'auto_build.%s.%s.%s.export.log' % (
            box_name, provider, datestamp))

    my_pid = os.getpid()
    sys.stdout.write('%s: Running halt/destroy, then %r\n' % (
        my_pid, build_cmd))
    sys.stdout.flush()
    with open(build_log_path, 'wb', 0) as build_log_fh:
        subprocess.call(halt_cmd, stdout=build_log_fh,
                        stderr=subprocess.STDOUT, cwd=MY_DIR)
        subprocess.call(destroy_cmd, stdout=build_log_fh,
                        stderr=subprocess.STDOUT, cwd=MY_DIR)
        build = subprocess.Popen(build_cmd,
                                 stdout=build_log_fh,
                                 stderr=subprocess.STDOUT,
                                 cwd=MY_DIR)
        build.wait()
    if build.returncode == 0:
        # Now export it (protected by a box-name lock
        if os.path.exists(exp_box_path):
            os.unlink(exp_box_path)
        if os.path.exists(final_box_path):
            os.unlink(final_box_path)
        with BOX_LOCKS[box_name]:
            export_cmd = VEEWEE_CMD_BASE + [provider, 'export', box_name]
            sys.stdout.write('%s: Running %r\n' % (my_pid, export_cmd))
            sys.stdout.flush()
            with open(export_log_path, 'wb', 0) as export_log_fh:
                export = subprocess.Popen(export_cmd,
                                          stdout=export_log_fh,
                                          stderr=subprocess.STDOUT,
                                          cwd=MY_DIR)
                export.wait()
            if export.returncode == 0:
                if os.path.exists(exp_box_path):
                    os.rename(exp_box_path, final_box_path)
                    return provider, box_name, 0, ''
                else:
                    return provider, box_name, 42, export_log_path
            else:
                return provider, box_name, export.returncode, export_log_path
    else:
        return provider, box_name, build.returncode, build_log_path


if __name__ == '__main__':
    now = datetime.now()
    def_datestamp = '%4d%02d%02d' % (now.year, now.month, now.day)

    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description='Automatically build one or more veeweebox in parallel')
    parser.add_argument('--job-count', '-j',
                        type=int, default=2,
                        help='The number of boxes to build in parallel')
    parser.add_argument('--providers', '-p', type=str, default='vbox',
                        help='"vbox", "fusion", or "vbox,fusion"')
    parser.add_argument('--definitions-dir', '-d', type=str,
                        default=os.path.join(MY_DIR, '..', 'ss-veewee',
                                             'definitions'))
    parser.add_argument('--datestamp', '-s', type=str,
                        default=def_datestamp,
                        help='Date-stamp for built boxes')
    parser.add_argument('--log-dir', '-l',
                        default='logs' if os.path.isdir('logs') else '/tmp',
                        help='Store log files in this dir')
    parser.add_argument('box_regexes', nargs='+',
                        help='Build boxes matching any of these regexes')

    args = parser.parse_args()

    args.providers = args.providers.split(',')

    if not os.path.isdir(args.definitions_dir):
        parser.error('Missing or not a directory: %r'
                     % args.definitions_dir)

    if not os.path.isdir(args.log_dir):
        parser.error('--log-dir %r was not a directory?!'
                     % args.log_dir)

    box_regexes = [re.compile(r) for r in args.box_regexes]
    args.boxes = [
        n for n in os.listdir(args.definitions_dir)
        if os.path.exists(os.path.join(args.definitions_dir, n,
                                       'definition.rb')) and
        any(r.search(n) for r in box_regexes)]

    if not args.boxes:
        parser.error('No boxes matched %r' % args.box_regexes)

    # Prevent concurrent box export based on box name
    global BOX_LOCKS
    BOX_LOCKS = {n: multiprocessing.Lock() for n in args.boxes}

    print "Building %r for %r in %d workers..." % (
        args.boxes, args.providers, args.job_count)

    pool = multiprocessing.Pool(args.job_count)
    results = pool.imap_unordered(build_box, job_gen(args))

    for provider, box_name, rc, err_log_path in results:
        if rc == 0:
            print "SUCCESS built %s for %s" % (box_name, provider)
        else:
            print ("FAILURE building or exporting %s for %s\n"
                   "    SEE: less -r %s" % (box_name, provider,
                                            err_log_path))
        sys.stdout.flush()
        destroy_cmd = VEEWEE_CMD_BASE + [provider, 'destroy', box_name]
        destroy = subprocess.Popen(destroy_cmd,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT,
                                   cwd=MY_DIR)
        d_stdout_err, _ = destroy.communicate()
        if destroy.returncode != 0:
            print 'WARNING failed to destroy %s %s\nOUTPUT:\n\n%s' % (
                provider, box_name, d_stdout_err)
            sys.stdout.flush()
