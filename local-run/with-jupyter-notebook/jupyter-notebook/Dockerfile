FROM jupyter/datascience-notebook:python-3.11.6

ENV PYTHON_SHARED_LIB_PATH="${HOME}/python/lib"
ENV PYTHONPATH="${PYTHONPATH}:${PYTHON_SHARED_LIB_PATH}"
ENV PIP_TARGET="${PYTHON_SHARED_LIB_PATH}"

RUN mkdir -p "${PYTHON_SHARED_LIB_PATH}"

RUN pip install --upgrade pip
RUN pip install --upgrade matplotlib scipy scikit-learn numba seaborn
RUN pip install --upgrade pandas "numpy==1.24.4"
RUN echo 'umask 0007' >> "${HOME}/.bashrc"