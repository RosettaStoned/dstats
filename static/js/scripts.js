$(document).ready(function() {

  var protocol = window.location.protocol
  var host = window.location.host

  var wsProtocol = protocol == 'https:' ? 'wss://' : 'ws://'
  var wsUri = [
    wsProtocol,
    host,
    '/docker-stats/ws'
  ].join('')

  conn = new WebSocket(wsUri);

  conn.onopen = function(e) {
    console.log('Connected.');
  };

  conn.onmessage = function(e) {

    stats_json = e.data
    console.log('Received: ' + stats_json);

    stats = JSON.parse(stats_json)
    data = statsDataTable(stats)
    drawTable(data)

  };

  conn.onclose = function(e) {
    console.log('Disconnected.');
    conn = null;
  };
 

  google.charts.load('current', {'packages':['corechart', 'table']});
  google.charts.setOnLoadCallback(drawTable);

  function statsDataTable(stats) {

    table = [
      [
        { label: 'CONTAINER ID', id: 'container_id' },
        { label: 'NAME', id: 'container_name' },
        { label: 'CPU %', id: 'cpu_usege_perc' },
        { label: 'MEMORY USAGE / LIMIT', id: 'memory_usage_limit' },
        { label: 'MEM %', id: 'memory_usage_perc' },
        { label: 'NET I/O', id: 'netio' },
        { label: 'BLOCK I/O', id: 'blkio' },
      ],
    ];

    for(var i=0; i < stats.length; i++) {

        containerStats = stats[i]

        memoryUsageLimit = [ 
          containerStats['memory_stats']['usage_hr'],
          '/',
          containerStats['memory_stats']['limit_hr']
        ].join('');

        netio = [
          containerStats['network_stats']['received_bytes_hr'],
          '/',
          containerStats['network_stats']['transceived_bytes_hr'],
        ].join('');

        blkio = [
          containerStats['blkio_stats']['read_bytes_hr'],
          '/',
          containerStats['blkio_stats']['wrote_bytes_hr']
        ].join('');

        row = [
          containerStats['container']['Id'],
          containerStats['container']['Name'],
          containerStats['cpu_stats']['cpu_usage_perc'],
          memoryUsageLimit,
          containerStats['memory_stats']['perc'],
          netio,
          blkio
        ];

        table.push(row);
    }

    var data = new google.visualization.arrayToDataTable(table);

    return data

  }

  function drawTable(data) {
    if(typeof data === 'undefined') {
      data = statsDataTable([]);
    }

    var table = new google.visualization.Table(document.getElementById('table_div'));
    table.draw(data, {showRowNumber: true, width: '100%', height: '100%'});

    google.visualization.events.addListener(table, 'select', function() {

      selection = table.getSelection()
      if(selection.length === 0) {
        return
      }

      var row = selection[0].row;
      alert('You selected ' + data.getValue(row, 0));
    });
  }


});
