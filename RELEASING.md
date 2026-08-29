# Release checklist

This checklist keeps the GitHub release, PyPI package, documentation, and Zenodo archive aligned.

## Prepare

1. Start from a clean branch based on the current `main` branch.
2. Set the same version in `pyproject.toml`, `src/mzmlpy/__init__.py`, and `CITATION.cff`.
3. Move the user-visible changes from `Unreleased` into a dated version section in `CHANGELOG.md`.
4. Confirm the package classifiers, dependency floors, citation metadata, and documentation describe the candidate accurately.
5. Run the full local gate:

   ```bash
   just lint
   just ty
   just test-cov
   just docs-build
   uv build
   ```

6. Check both distributions with Twine and inspect their file lists.
7. Install the wheel into a clean environment and verify the public version, imports, and embedded-index writer.
8. Merge the reviewed release branch into `main` and wait for Python 3.12, 3.13, and 3.14 CI to pass.

## Publish

1. Create a GitHub release tagged `vX.Y.Z` at the reviewed commit on `main`.
2. Use the matching `CHANGELOG.md` section as the release notes.
3. The release workflow builds and publishes the package to PyPI with the configured project token.
4. Confirm the new files and metadata on PyPI, then install the published wheel in a clean environment.
5. Wait for Zenodo to archive the GitHub release and verify its title, creators, ORCIDs, version, license, repository, and files.
6. Add the version-specific Zenodo citation to the README in a follow-up commit.

Publishing package files and a Zenodo record cannot be undone through the ordinary release workflow. Review the final tag target and metadata before publishing the GitHub release.
