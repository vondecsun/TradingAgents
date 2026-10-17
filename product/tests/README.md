Run from the repository root:

    python -m pip install -r product/requirements-test.txt
    python -m pytest product/tests -q -o addopts=''

Tests use temporary SQLite databases and synthetic fixtures. They never submit
real orders or call paid model APIs. Product tests are independent of the upstream
research dependencies. Running the entire upstream suite requires its own extras.

DOM integration test (Node 22+, no graphical browser):

    npm install --prefix product --ignore-scripts
    python product/tests/run_frontend.py

This creates an isolated temporary server/database, then tests registration,
loading demo data, search, analysis/report, paper order/fill, test subscription,
settings, data page and logout. It is not visual or native-device testing.
