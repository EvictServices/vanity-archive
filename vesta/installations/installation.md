### Installation

```bash
# Git clone the repo and fill out enviroment variables.

git clone https://github.com/EvictServices/vesta.git
cd vesta
cp .env.example .env

# Install prerequisite 

# Install postgres & redis.

sudo apt upgrade && sudo apt install redis postgresql -y

# Change to the postgres user and enter the environment.

sudo su postgres
psql

# Create the database.

CREATE DATABASE evict;
ALTER ROLE postgres WITH PASSWORD 'admin';

# Create the root role to make entering the data easier.

CREATE ROLE root WITH LOGIN SUPERUSER;
ALTER ROLE root WITH PASSWORD 'admin';

# Dump the data into postgres.

pg_dump -d dbname -f file.sql

---
### Install solutions

## Minio

### Make the minio setup and enter the directory.

sudo mkdir minio-setup && cd minio-setup

### Setup minio using the file located in /root/vesta/installations/minio-setup.yml

### Cloudflare Warp

# Add cloudflare gpg key.
curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | sudo gpg --yes --dearmor --output /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg

# Add this repo to your apt repositories.
echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/cloudflare-client.list

# Install.
sudo apt-get update && sudo apt-get install cloudflare-warp

# Register the client.
warp-cli registration new

# Change the mode to proxy.
warp-cli mode proxy

# Connect to the proxy.
warp-cli connect

---
### Running the bot.

# Install python requirements.

pip install -r requirements.txt

# Run the bot.

python -m vesta