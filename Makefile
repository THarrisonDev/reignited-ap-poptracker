# PopTracker pack — packaging.
#
# Assembles the pack PopTracker loads: manifest, settings, license, and the
# runtime trees. Dev scripts, PACKS.md and README.md are repo-only, never ship.

PACK    := spyro_reignited_ap
DIST    := dist
PKG     := $(DIST)/$(PACK)
RUNTIME := scripts items locations layouts maps images

.PHONY: check package clean

# Verify the generated files match the world data (needs the sibling world/).
check:
	python3 gen_pack.py --check

package: check
	rm -rf $(DIST)
	mkdir -p $(PKG)
	cp -f manifest.json settings.json LICENSE $(PKG)/
	cp -a $(RUNTIME) $(PKG)/
	@echo "packaged $(abspath $(PKG))"

clean:
	rm -rf $(DIST) __pycache__
