module.exports = {
  apps: [{
    name: 'vanity',
    script: '/comminate/vanity/.venv/bin/python',
    args: '-m vesta',
    interpreter: '/comminate/vanity/.venv/bin/python',
    cwd: '/comminate/vanity',
    env: {
      NODE_ENV: 'production',
      PYTHONPATH: '/comminate/vanity'
    }
  }]
};
