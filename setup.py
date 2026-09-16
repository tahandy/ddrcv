from setuptools import setup, find_packages

setup(
    name='ddrcv',
    version='0.1.0',
    author='Zvidun',
    author_email='none.of@your.business',
    description='Computer vision utilities to interrogate video feed for tournament enhancement',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/tahandy/ddrcv',
    packages=find_packages(),
    package_data={'ddrcv.score': ['fonts/*/*.png'], 'ddrcv.state': ['tbd5/*.pkl'], 'ddrcv.workbench': ['templates/*.html', 'static/*']},
    python_requires='>=3.10',
)