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
    containerId, 
    '/ws'
  ].join('')


  google.charts.load('current', {'packages':['corechart', 'table']});

  conn = new WebSocket(wsUri);

  statsSamples = FixedQueue(10, [])

  conn.onopen = function(e) {
    console.log('Connected.');
  };

  conn.onmessage = function(e) {
    stats_json = e.data;
    stats = JSON.parse(stats_json);
    console.log(stats)
    statsSamples.push(stats);
    drawMemoryChart(statsSamples);
  };

  conn.onclose = function(e) {
    console.log('Disconnected.');
    conn = null;
  };


  function byteFormatter(options) {
    var log1024 = Math.log(1024);
    this.scaleSuffix = [
      "B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB"
    ];
    this.formatValue = function ( value ) {
      var scale = Math.floor(Math.log(value)/log1024);
      var scaleSuffix = this.scaleSuffix[scale];
      var scaledValue = value / Math.pow(1024, scale);
      return Math.round( scaledValue * 100 ) / 100 + " " + scaleSuffix;
    };
    this.format = function( dt, c ) {
      var rows = dt.getNumberOfRows();
      for ( var r = 0; r < rows; ++r ) {
        var v = dt.getValue(r,c);
        var fv = this.formatValue(v);
        dt.setFormattedValue(r,c,fv);
      }
    };
  }


  function drawMemoryChart(statsSamples) {

    var data = new google.visualization.DataTable();
    data.addColumn('datetime', 'Time');
    data.addColumn('number', 'Memory Usage');
    data.addColumn('number', 'Memory Limit');

    for(var i = 0; i < statsSamples.length; i++) {
      statsSample = statsSamples[i];

      timestamp = new Date(statsSample['preread']);
      usage = statsSample['memory_stats']['usage'];
      limit = statsSample['memory_stats']['limit'];

      row = [
        timestamp,
        usage,
        limit
      ]

      data.addRow(row);
    }

    var ranges = data.getColumnRange(2);

    var formatter = new byteFormatter();
    formatter.format(data,1);
    formatter.format(data,2);
    var max = ranges.max * 1;

    var options = {
      title: 'Memory Usage',
      curveType: 'function',
      hAxis: {
        title: 'Time'
      },
      vAxis: {
        title: 'Memory',
        ticks: [
          { v:0 },
          { v:max*0.2, f:formatter.formatValue(max*0.2) },
          { v:max*0.4, f:formatter.formatValue(max*0.4) },
          { v:max*0.6, f:formatter.formatValue(max*0.6) },
          { v:max*0.8, f:formatter.formatValue(max*0.8) },
          { v:max, f:formatter.formatValue(max) }
        ]
      }
    };


    var chart_elem = document.getElementById('memory_usage_chart');
    var chart = new google.visualization.LineChart(chart_elem);

    chart.draw(data, options);

  }


});
