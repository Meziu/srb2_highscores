function get_server_info(callback) {
    fetch(api_url + "/server_info")
        .then(response => {
            return response.json()
        }).then(callback)
}

var players_table = document.getElementById("players_table")
var server_name = document.getElementById("server_name")
var map_title = document.getElementById("map_title")

function update_background(image) {
    if (image && image != "None") {
        document.body.style.backgroundImage = "url('" + static_dir + "/img/" + image + "')"
    }
}

function update_info_page() {
    get_server_info(data => {
        map_title.innerHTML = data.map.name
        server_name.innerHTML = data.servername
        players_table.innerHTML = ""
        update_background(data.map.image)
        data.players.forEach(player => {
            var tr = document.createElement('tr')
            tr.innerHTML = "<td>" + player.name.escape() + "</td><td>" + player.skin.escape() + "</td>"
            players_table.appendChild(tr)
        })
    })
}
