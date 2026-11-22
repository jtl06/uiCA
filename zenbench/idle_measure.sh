#!/bin/bash
# Run a measurement only while the machine is idle: waits until the 1-minute load average is below 0.3 (checked 3 times, 20 s apart),
# runs the command, and repeats it (up to 5 times) if the load rose during the run.   Usage: idle_measure.sh COMMAND...
for attempt in 1 2 3 4 5; do
   ok=0
   while [ $ok -lt 3 ]; do
      l=$(cut -d' ' -f1 /proc/loadavg)
      if awk "BEGIN{exit !($l < 0.3)}"; then ok=$((ok+1)); else ok=0; fi
      [ $ok -lt 3 ] && sleep 20
   done
   "$@" || exit 1
   l=$(cut -d' ' -f1 /proc/loadavg)
   awk "BEGIN{exit !($l < 1.0)}" && exit 0
   echo "load rose to $l during the run; repeating" >&2
done
exit 2
