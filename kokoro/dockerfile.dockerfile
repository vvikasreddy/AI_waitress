FROM continuumio/miniconda3

# copy and build kokoro env
COPY environment.yml /tmp/
RUN conda env create -f /tmp/environment.yml \
 && conda clean -afy

# ensure 'conda run' works by default
SHELL ["conda", "run", "-n", "kokoro", "/bin/bash", "-lc"]

WORKDIR /app
COPY . /app

# replace with whatever script you need to launch
CMD ["python", "demo.py"]
