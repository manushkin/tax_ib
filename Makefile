init:
	pip install pipenv --upgrade
	pipenv install --dev

test: test2 test3
	pipenv run flake8 tax_ib.py

test2:
	python2 -m doctest tax_ib.py
	python2 -m unittest tax_ib

test3:
	python3 -m doctest tax_ib.py
	python3 -m unittest tax_ib

.PHONY: init test test2 test3
