import os
import sys
import subprocess
import re
try:
    from hash import md5
except ImportError:
    import md5

import sphinx

import distutils
import numpy.distutils

try:
    from paver.tasks import VERSION as _PVER
    if not _PVER >= '1.0':
        raise RuntimeError("paver version >= 1.0 required (was %s)" % _PVER)
except ImportError, e:
    raise RuntimeError("paver version >= 1.0 required")

import paver
import paver.doctools
import paver.path
from paver.easy import options, Bunch, task, needs, dry, sh, call_task

setup_py = __import__("setup")
FULLVERSION = setup_py.FULLVERSION

# Wine config for win32 builds
WINE_SITE_CFG = ""
WINE_PY25 = "/home/david/.wine/drive_c/Python25/python.exe"
WINE_PY26 = "/home/david/.wine/drive_c/Python26/python.exe"
WINE_PYS = {'2.6' : WINE_PY26, '2.5': WINE_PY25}

PDF_DESTDIR = paver.path.path('build') / 'pdf'
HTML_DESTDIR = paver.path.path('build') / 'html'

RELEASE = 'doc/release/1.3.0-notes.rst'
LOG_START = 'tags/1.2.0'
LOG_END = 'master'
BOOTSTRAP_DIR = "bootstrap"
BOOTSTRAP_PYEXEC = "%s/bin/python" % BOOTSTRAP_DIR
BOOTSTRAP_SCRIPT = "%s/bootstrap.py" % BOOTSTRAP_DIR

DMG_CONTENT = paver.path.path('numpy-macosx-installer') / 'content'

options(sphinx=Bunch(builddir="build", sourcedir="source", docroot='doc'),
        virtualenv=Bunch(script_name=BOOTSTRAP_SCRIPT))

# Bootstrap stuff
@task
def bootstrap():
    """create virtualenv in ./install"""
    install = paver.path.path(BOOTSTRAP_DIR)
    if not install.exists():
        install.mkdir()
    call_task('paver.virtual.bootstrap')
    sh('cd %s; %s bootstrap.py' % (BOOTSTRAP_DIR, sys.executable))

@task
def clean():
    """Remove build, dist, egg-info garbage."""
    d = ['build', 'dist', 'numpy.egg-info']
    for i in d:
        paver.path.path(i).rmtree()

    (paver.path.path('doc') / options.sphinx.builddir).rmtree()

@task
def clean_bootstrap():
    paver.path.path('bootstrap').rmtree()

# NOTES/Changelog stuff
def compute_md5():
    released = paver.path.path('installers').listdir()
    checksums = []
    for f in released:
        m = md5.md5(open(f, 'r').read())
        checksums.append('%s  %s' % (m.hexdigest(), f))

    return checksums

def write_release_task(filename='NOTES.txt'):
    source = paver.path.path(RELEASE)
    target = paver.path.path(filename)
    if target.exists():
        target.remove()
    source.copy(target)
    ftarget = open(str(target), 'a')
    ftarget.writelines("""
Checksums
=========

""")
    ftarget.writelines(['%s\n' % c for c in compute_md5()])

def write_log_task(filename='Changelog'):
    st = subprocess.Popen(
            ['git', 'svn', 'log',  '%s..%s' % (LOG_START, LOG_END)],
            stdout=subprocess.PIPE)

    out = st.communicate()[0]
    a = open(filename, 'w')
    a.writelines(out)
    a.close()

@task
def write_release():
    write_release_task()

@task
def write_log():
    write_log_task()

# Doc stuff
@task
@needs('paver.doctools.html')
def html(options):
    """Build numpy documentation and put it into build/docs"""
    builtdocs = paver.path.path("doc") / options.sphinx.builddir / "html"
    HTML_DESTDIR.rmtree()
    builtdocs.copytree(HTML_DESTDIR)

def _latex_paths():
    """look up the options that determine where all of the files are."""
    opts = options
    docroot = paver.path.path(opts.get('docroot', 'docs'))
    if not docroot.exists():
        raise BuildFailure("Sphinx documentation root (%s) does not exist."
                % docroot)
    builddir = docroot / opts.get("builddir", ".build")
    builddir.mkdir()
    srcdir = docroot / opts.get("sourcedir", "")
    if not srcdir.exists():
        raise BuildFailure("Sphinx source file dir (%s) does not exist"
                % srcdir)
    latexdir = builddir / "latex"
    latexdir.mkdir()
    return Bunch(locals())

@task
def latex():
    """Build samplerate's documentation and install it into
    scikits/samplerate/docs"""
    paths = _latex_paths()
    sphinxopts = ['', '-b', 'latex', paths.srcdir, paths.latexdir]
    #dry("sphinx-build %s" % (" ".join(sphinxopts),), sphinx.main, sphinxopts)
    subprocess.check_call(["make", "latex"], cwd="doc")

@task
@needs('latex')
def pdf():
    paths = _latex_paths()
    def build_latex():
        subprocess.check_call(["make", "all-pdf"], cwd=paths.latexdir)
    dry("Build pdf doc", build_latex)

    PDF_DESTDIR.rmtree()
    PDF_DESTDIR.makedirs()

    user = paths.latexdir / "numpy-user.pdf"
    user.copy(PDF_DESTDIR / "userguide.pdf")
    ref = paths.latexdir / "numpy-ref.pdf"
    ref.copy(PDF_DESTDIR / "reference.pdf")

@task
def sdist():
    # To be sure to bypass paver when building sdist... paver + numpy.distutils
    # do not play well together.
    sh('python setup.py sdist --formats=gztar,zip')

@task
@needs('clean')
def bdist_wininst_26():
    _bdist_wininst(pyver='2.6')

@task
@needs('clean')
def bdist_wininst_25():
    _bdist_wininst(pyver='2.5')

@task
@needs('bdist_wininst_25', 'bdist_wininst_26')
def bdist_wininst():
    pass

@task
@needs('clean', 'bdist_wininst')
def winbin():
    pass

def _bdist_wininst(pyver):
    site = paver.path.path('site.cfg')
    exists = site.exists()
    try:
        if exists:
            site.move('site.cfg.bak')
        a = open(str(site), 'w')
        a.writelines(WINE_SITE_CFG)
        a.close()
        sh('%s setup.py build -c mingw32 bdist_wininst' % WINE_PYS[pyver])
    finally:
        site.remove()
        if exists:
            paver.path.path('site.cfg.bak').move(site)

# Mac OS X installer
def macosx_version():
    if not sys.platform == 'darwin':
        raise ValueError("Not darwin ??")
    st = subprocess.Popen(["sw_vers"], stdout=subprocess.PIPE)
    out = st.stdout.readlines()
    ver = re.compile("ProductVersion:\s+([0-9]+)\.([0-9]+)\.([0-9]+)")
    for i in out:
        m = ver.match(i)
        if m:
            return m.groups()

def mpkg_name():
    maj, min = macosx_version()[:2]
    pyver = ".".join([str(i) for i in sys.version_info[:2]])
    return "numpy-%s-py%s-macosx%s.%s.mpkg" % \
            (FULLVERSION, pyver, maj, min)

def dmg_name():
    maj, min = macosx_version()[:2]
    pyver = ".".join([str(i) for i in sys.version_info[:2]])
    return "numpy-%s-py%s-macosx%s.%s.dmg" % \
            (FULLVERSION, pyver, maj, min)

@task
def bdist_mpkg():
	sh("python setupegg.py bdist_mpkg")

@task
@needs("bdist_mpkg", "pdf")
def dmg():
    pyver = ".".join([str(i) for i in sys.version_info[:2]])

    dmg_n = dmg_name()
    dmg = paver.path.path('numpy-macosx-installer') / dmg_n
    if dmg.exists():
        dmg.remove()

	# Clean the image source
    content = DMG_CONTENT
    content.rmtree()
    content.mkdir()

    # Copy mpkg into image source
    mpkg_n = mpkg_name()
    mpkg_tn = "numpy-%s-py%s.mpkg" % (FULLVERSION, pyver)
    mpkg_source = paver.path.path("dist") / mpkg_n
    mpkg_target = content / mpkg_tn
    mpkg_source.copytree(content / mpkg_tn)

    # Copy docs into image source

    #html_docs = HTML_DESTDIR
    #html_docs.copytree(content / "Documentation" / "html")

    pdf_docs = DMG_CONTENT / "Documentation"
    pdf_docs.rmtree()
    pdf_docs.makedirs()

    user = PDF_DESTDIR / "userguide.pdf"
    user.copy(pdf_docs / "userguide.pdf")
    ref = PDF_DESTDIR / "reference.pdf"
    ref.copy(pdf_docs / "reference.pdf")

    # Build the dmg
    cmd = ["./create-dmg", "--window-size", "500", "500", "--background",
        "art/dmgbackground.png", "--icon-size", "128", "--icon", mpkg_tn, 
        "125", "320", "--icon", "Documentation", "375", "320", "--volname", "numpy",
        dmg_n, "./content"]
    subprocess.check_call(cmd, cwd="numpy-macosx-installer")
    
@task
def simple_dmg():
    # Build the dmg
    image_name = "numpy-%s.dmg" % FULLVERSION
    image = paver.path.path(image_name)
    image.remove()
    cmd = ["hdiutil", "create", image_name, "-srcdir", str(builddir)]
    sh(" ".join(cmd))