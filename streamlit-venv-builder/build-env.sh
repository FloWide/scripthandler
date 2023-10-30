 #!/bin/bash

WHEELS_DIR="./wheel_files"

if [ -d $VENV ]; then
    rm -R $VENV
fi

python -m venv $VENV
"$VENV/bin/pip" install -U pip
"$VENV/bin/pip" install wheel
"$VENV/bin/pip" install -r requirements.txt
find $WHEELS_DIR -name *.whl | xargs --no-run-if-empty "$VENV/bin/pip" install