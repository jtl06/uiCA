#!/usr/bin/env bash

# the XED Python module needs the Python headers and setuptools
python3 -c 'import os, sys, sysconfig, setuptools; sys.exit(not os.path.exists(os.path.join(sysconfig.get_paths()["include"], "Python.h")))' 2>/dev/null || {
   echo 'setup.sh needs the Python headers and setuptools (Ubuntu: sudo apt-get install python3-dev python3-setuptools)'; exit 1; }

git submodule update --init || exit 1
cd XED-to-XML
./mfile.py --opt=2 --no-encoder pymodule || exit 1
cp xed.* ..
cd ..
git submodule deinit -f --all
rm -rf .git/modules/*

wget https://www.uops.info/instructions.xml || exit 1
./convertXML.py instructions.xml || exit 1
rm instructions.xml
