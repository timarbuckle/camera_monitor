require Logger

defmodule CameraMonitor do
  @moduledoc """
  Monitors UniFi camera online statuses and power-cycles PoE switch ports if they go offline.
  """

  # --- CONFIGURATION ---
  @unifi_host "10.0.0.1"
  @site_id "default"
  @switch_mac "e0:63:da:2e:80:74"
  @base_url "https://#{@unifi_host}"

  @cameras_to_monitor [
    %{mac: "1c:6a:1b:8c:45:3f", ip: "10.0.3.248", port: 5, name: "Front Entry and Yard"},
    %{mac: "28:70:4e:1d:77:13", ip: "10.0.3.155", port: 6, name: "BBQ area and Pool Slider"},
    %{mac: "28:70:4e:1d:73:d1", ip: "10.0.3.146", port: 7, name: "Courtyard and Sliders"},
    %{mac: "1c:6a:1b:8c:47:67", ip: "10.0.3.14", port: 8, name: "Pool Spa and Rear Fence Line"}
  ]

  def run do
    # Load environment variables
    Dotenvy.source!([".env", System.get_env()])
    unifi_user = System.get_env("UNIFI_USER")
    unifi_pass = System.get_env("UNIFI_PASS")

    case get_unifi_client(unifi_user, unifi_pass) do
      {:ok, client} ->
        check_cameras_and_cycle(client)

      {:error, reason} ->
        Logger.error("Failed to initialize UniFi connection: #{inspect(reason)}")
    end
  end

  # Authenticates and builds a pre-configured Req client instance (replacing requests.Session)
  defp get_unifi_client(user, pass) do
    # Configure base client options (disable SSL verification equivalent to urllib3.disable_warnings)
    base_client = Req.new(
      base_url: @base_url,
      connect_options: [transport_options: [verify: :verify_none]],
      headers: [
        {"referer", "#{@base_url}/"},
        {"content-type", "application/json"}
      ]
    )

    case Req.post(base_client, url: "/api/auth/login", json: %{username: user, password: pass}) do
      {:ok, %Req.Response{status: 200, headers: headers} = response} ->
        # Extract CSRF token if present
        case Enum.find(headers, fn {k, _v} -> String.downcase(k) == "x-csrf-token" end) do
          {_key, token} ->
            {:ok, Req.update(base_client, headers: [{"x-csrf-token", token}])}
          nil ->
            {:ok, base_client}
        end

      {:ok, response} ->
        {:error, "Login failed with status #{response.status}"}

      {:error, exception} ->
        {:error, exception}
    end
  end

  defp check_cameras_and_cycle(client) do
    url = "/proxy/network/api/s/#{@site_id}/stat/sta"

    case Req.get(client, url: url) do
      {:ok, %Req.Response{status: 200, body: %{"data" => devices}}} ->
        # Build a Map lookup by downcased MAC address (Equivalent to Python dict comprehension)
        device_map = Map.new(devices, fn device -> {String.downcase(device["mac"]), device} end)

        Enum.each(@cameras_to_monitor, fn cam ->
          process_camera(client, cam, device_map)
        end)

      {:ok, response} ->
        Logger.error("Failed to fetch clients. HTTP #{response.status}")

      {:error, error} ->
        Logger.error("Error during processing: #{inspect(error)}")
    end
  end

  defp process_camera(client, cam, device_map) do
    cam_mac = String.downcase(cam.mac)

    case Map.fetch(device_map, cam_mac) do
      {:ok, device_data} ->
        is_online = camera_online?(device_data)
        Logger.info("[#{cam.name}] Status flag: #{if is_online, do: "ONLINE", else: "OFFLINE"}")

        if not is_online do
          Logger.warning("[ALERT] #{cam.name} is explicitly flagged OFFLINE. Cycling port #{cam.port}...")
          power_cycle_poe_port(client, cam.port)
        end

      :error ->
        Logger.warning("[WARN] #{cam.name} (#{cam_mac}) not found in UniFi database. Check MAC.")
    end
  end

  # Clean data navigation using Elixir's kernel macro `get_in/2`
  defp camera_online?(device_data) do
    ucore_info = get_in(device_data, ["unifi_device_info_from_ucore"]) || %{}
    
    device_state = String.upcase(ucore_info["device_state"] || "")
    ucore_status = String.downcase(ucore_info["ucore_device_status"] || "")

    device_state == "CONNECTED" or ucore_status == "online"
  end

  defp power_cycle_poe_port(client, port_index) do
    url = "/proxy/network/api/s/#{@site_id}/cmd/devmgr"
    payload = %{
      mac: String.downcase(@switch_mac),
      port_idx: port_index,
      cmd: "power-cycle"
    }

    case Req.post(client, url: url, json: payload) do
      {:ok, %Req.Response{status: 200}} ->
        Logger.info("[SUCCESS] Port #{port_index} power cycled.")

      {:ok, response} ->
        Logger.error("[ERROR] Power cycle command failed: #{inspect(response.body)}")

      {:error, error} ->
        Logger.error("[ERROR] Network failure during power cycle: #{inspect(error)}")
    end
  end
end

# Execute the script
CameraMonitor.run()
