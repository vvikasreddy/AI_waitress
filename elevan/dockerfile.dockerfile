FROM continuumio/miniconda3

COPY environment.yml /tmp/
RUN conda env create -f /tmp/environment.yml \
 && conda clean -afy

SHELL ["conda", "run", "-n", "elevan", "/bin/bash", "-lc"]

WORKDIR /app
COPY . /app

CMD ["python", "demo.py"]
