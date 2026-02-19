-- ccsds_style_telemetry_dissector.lua
local plugin_info = {
    version = "1.0.0",
    author = "Wesley Jeong",
    description = "Example CCSDS-style telemetry dissector (Wireshark Lua)",
  }
  set_plugin_info(plugin_info)
  
  local PRIMARY_LEN = 6
  local SECONDARY_LEN = 14
  
  local p_tlm = Proto("ccsds_tlm_example", "CCSDS Telemetry (Example)")
  
  local f_msg_id = ProtoField.uint8("ccsds_tlm_example.msg_id", "Message ID", base.HEX)
  local f_seq    = ProtoField.uint16("ccsds_tlm_example.seq", "Sequence", base.DEC)
  
  -- Example payload fields (keep these generic)
  local f_status = ProtoField.uint32("ccsds_tlm_example.status", "Status", base.HEX)
  local f_temp   = ProtoField.uint32("ccsds_tlm_example.temp", "Temperature (raw)", base.DEC)
  local f_v      = ProtoField.uint32("ccsds_tlm_example.v", "Voltage (raw)", base.DEC)
  
  p_tlm.fields = { f_msg_id, f_seq, f_status, f_temp, f_v }
  
  function p_tlm.dissector(buffer, pinfo, tree)
    if buffer:len() < (PRIMARY_LEN + SECONDARY_LEN + 1) then return end
    pinfo.cols.protocol:set("CCSDS_TLM")
  
    local payload_off = PRIMARY_LEN + SECONDARY_LEN
    local msg_id = buffer(payload_off, 1):uint()
    local seq    = buffer(payload_off + 1, 2):uint()
  
    pinfo.cols.info:set(string.format("MsgID=0x%02X Seq=%d", msg_id, seq))
  
    local subtree = tree:add(p_tlm, buffer(payload_off), "CCSDS Telemetry (Example)")
    subtree:add(f_msg_id, buffer(payload_off, 1))
    subtree:add(f_seq,    buffer(payload_off + 1, 2))
  
    -- Example message formats
    if msg_id == 0x01 then
      subtree:add(f_status, buffer(payload_off + 4, 4))
    elseif msg_id == 0x02 then
      subtree:add(f_temp, buffer(payload_off + 4, 4))
      subtree:add(f_v,    buffer(payload_off + 8, 4))
    else
      subtree:add(buffer(payload_off + 4):tvb(), "Raw Payload (" .. (buffer:len() - (payload_off + 4)) .. " bytes)")
    end
  end
  
  ccsds_tlm_example = p_tlm
  