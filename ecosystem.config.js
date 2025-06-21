module.exports = {
  apps: [{
    name: 'vanity',
    script: 'python',
    args: '-m vesta',
    interpreter: '/root/vanity/.venv/bin/python',
    cwd: '/root/vanity',
    env: {
      NODE_ENV: 'production',
      PYTHONPATH: '/root/vanity'
    }
  }]
};