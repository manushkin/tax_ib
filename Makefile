init:
	python -m pip install --upgrade pip
	pip install -r requirements.txt
	pip install flake8

test: test2 test3
	flake8 tax_ib.py

test2:
	python2 -m doctest tax_ib.py
	python2 -m unittest tax_ib

test3:
	python3 -m doctest tax_ib.py
	python3 -m unittest tax_ib

.PHONY: init test test2 test3
