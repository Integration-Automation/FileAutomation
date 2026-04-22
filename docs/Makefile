# Minimal Sphinx Makefile
SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = source
BUILDDIR      = _build

.PHONY: help html clean html-zh-TW html-zh-CN html-all

help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS)

html:
	@$(SPHINXBUILD) -M html "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS)

html-zh-TW:
	@$(SPHINXBUILD) -b html source.zh-TW "$(BUILDDIR)/html-zh-TW" $(SPHINXOPTS)

html-zh-CN:
	@$(SPHINXBUILD) -b html source.zh-CN "$(BUILDDIR)/html-zh-CN" $(SPHINXOPTS)

html-all: html html-zh-TW html-zh-CN

clean:
	@$(SPHINXBUILD) -M clean "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS)
