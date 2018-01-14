$(document).ready(function() {

  var protocol = window.location.protocol
  var host = window.location.host
  var href = location.href

  var containerId = href.substr(href.lastIndexOf('/') + 1)
  var wsProtocol = protocol == 'https:' ? 'wss://' : 'ws://'

  var wsUri = [
    wsProtocol,
    host,
    '/containers/',
    containerId
  ].join('')

  conn = new WebSocket(wsUri);

  conn.onopen = function(e) {
    console.log('Connected.');
  };

  conn.onmessage = function(e) {

    stats_json = e.data
    console.log('Received: ' + stats_json);

    stats = JSON.parse(stats_json)
  };

  conn.onclose = function(e) {
    console.log('Disconnected.');
    conn = null;
  };

});
