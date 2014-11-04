#
# Copyright (c) 2014 Qualcomm Atheros, Inc.
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
#
# trace-cmd pktlog plugin for ath10k, QCA Linux wireless driver
#
# TODO:
#
# o create class for struct ieee80211_hdr each packet headers with
#   pack() and unpack() methods

import struct
import binascii

DEBUG = 1

CUR_PKTLOG_VER          = 10010
PKTLOG_MAGIC_NUM        = 7735225

IEEE80211_FCTL_TODS     = 0x0100
IEEE80211_FCTL_FROMDS   = 0x0200
TARGET_NUM_MSDU_DESC    = (1024 + 400)
MAX_PKT_INFO_MSDU_ID    = 192
PKTLOG_MAX_TXCTL_WORDS  = 57

ATH10K_PKTLOG_TYPE_TX_CTRL = 1
ATH10K_PKTLOG_TYPE_TX_STAT = 2
ATH10K_PKTLOG_TYPE_TX_MSDU_ID = 3
ATH10K_PKTLOG_TYPE_TX_FRM_HDR = 4
ATH10K_PKTLOG_TYPE_RX_STAT = 5
ATH10K_PKTLOG_TYPE_RC_FIND = 6
ATH10K_PKTLOG_TYPE_RC_UPDATE = 7
ATH10K_PKTLOG_TYPE_TX_VIRT_ADDR = 8
ATH10K_PKTLOG_TYPE_DBG_PRINT = 9

ATH10K_PKTLOG_FLG_TYPE_LOCAL_S = 0
ATH10K_PKTLOG_FLG_TYPE_REMOTE_S = 1
ATH10K_PKTLOG_FLG_TYPE_CLONE_S = 2
ATH10K_PKTLOG_FLG_TYPE_UNKNOWN_S = 3

# sizeof(ath10k_pktlog_txctl) = 12 + 4 * 57
ATH10K_PKTLOG_TXCTL_LEN = 240

msdu_len_tbl = {}
output_file = None
frm_hdr = None

def dbg(msg):
    if DEBUG == 0:
        return

    print msg

def hexdump(buf, prefix=None):
    s = binascii.b2a_hex(buf)
    s_len = len(s)
    result = ""

    if prefix == None:
        prefix = ""

    for i in range(s_len / 2):
        if i % 16 == 0:
            result = result + ("%s%04x: " % (prefix, i))

        result = result + (s[2*i] + s[2*i+1] + " ")

        if (i + 1) % 16 == 0:
            result = result + "\n"

    # FIXME: if len(s) % 16 == 0 there's an extra \n in the end

    return result

# struct ath10k_pktlog_hdr {
# 	unsigned short flags;
# 	unsigned short missed_cnt;
# 	unsigned short log_type;
# 	unsigned short size;
# 	unsigned int timestamp;
# 	unsigned char payload[0];
# } __attribute__((__packed__));
class Ath10kPktlogHdr:
    # 2 + 2 + 2 + 2 + 4 = 12
    hdr_len = 12
    struct_fmt = '<HHHHI'

    def unpack(self, buf, offset=0):
        (self.flags, self.missed_cnt, self.log_type,
         self.size, self.timestamp) = struct.unpack_from(self.struct_fmt, buf, 0)

        payload_len = len(buf) - self.hdr_len
        if payload_len != self.size:
            raise Exception('Payload length invalid: %d != %d' %
                            (payload_len, self.size))

        self.payload = buf[self.hdr_len:]

    # excludes payload, you have to write that separately!
    def pack(self):
        return struct.pack(self.struct_fmt,
                           self.flags,
                           self.missed_cnt,
                           self.log_type,
                           self.size,
                           self.timestamp)

    def __str__(self):
        return 'flags %04x miss %d log_type %d size %d timestamp %d\n' % \
            (self.flags, self.missed_cnt, self.log_type, self.size, self.timestamp)

    def __init__(self):
        self.flags = 0
        self.missed_cnt = 0
        self.log_type = 0
        self.size = 0
        self.timestamp = 0
        self.payload = []

def output_open():
    global output_file

    # apparently no way to close the file as the python plugin doesn't
    # have unregister() callback
    output_file = open('pktlog.dat', 'wb')

    buf = struct.pack('II', PKTLOG_MAGIC_NUM, CUR_PKTLOG_VER)
    output_write(buf)

def output_write(buf):
    global output_file

    output_file.write(buf)

def pktlog_tx_frm_hdr(frame):
    global frm_hdr

    try:
        # struct ieee80211_hdr
        (frame_control, duration_id, addr1a, addr1b, addr1c, addr2a, addr2b, addr2c, addr3a, addr3b, addr3c, seq_ctrl) = struct.unpack_from('<HHI2BI2BI2BH', frame, 0)
    except struct.error as e:
        dbg('failed to parse struct ieee80211_hdr: %s' % (e))
        return

    if frame_control & IEEE80211_FCTL_TODS:
        bssid_tail = (addr1b << 8) | addr1c
        sa_tail = (addr2b << 8) | addr2c
        da_tail = (addr3b << 8) | addr3c
    elif frame_control & IEEE80211_FCTL_FROMDS:
        bssid_tail = (addr2b << 8) | addr2c
        sa_tail = (addr3b << 8) | addr3c
        da_tail = (addr1b << 8) | addr1c
    else:
        bssid_tail = (addr3b << 8) | addr3c
        sa_tail = (addr2b << 8) | addr2c
        da_tail = (addr1b << 8) | addr1c

    resvd = 0

    frm_hdr = struct.pack('HHHHHH', frame_control, seq_ctrl, bssid_tail,
                          sa_tail, da_tail, resvd)
    dbg('frm_hdr %d B' % len(frm_hdr))

def pktlog_tx_ctrl(buf):
    global frm_hdr

    hdr = Ath10kPktlogHdr()
    hdr.unpack(buf)
    hdr.size = ATH10K_PKTLOG_TXCTL_LEN

    output_write(hdr.pack())
    
    # write struct ath10k_pktlog_frame
    if frm_hdr:
        output_write(frm_hdr)
    else:
        tmp = struct.pack('HHHHHH', 0, 0, 0, 0, 0, 0)
        output_write(tmp)

    # write unsigned int txdesc_ctl[PKTLOG_MAX_TXCTL_WORDS]
    # FIXME: check that length is correct
    output_write(buf[12:])

def pktlog_tx_msdu_id(buf):
    global msdu_len_tbl

    hdr = Ath10kPktlogHdr()
    hdr.unpack(buf)
    hdr.size = 4 + (192 / 8) + 2 * 192

    # write struct ath10k_pktlog_hdr
    output_write(hdr.pack())

    # parse struct msdu_id_info
    # hdr (12) + num_msdu (4) + bound_bmap (24) = 40
    msdu_info = hdr.payload[0:28]
    id = hdr.payload[28:]
    num_msdu, = struct.unpack_from('I', msdu_info)
    output_write(msdu_info)

    for i in range(MAX_PKT_INFO_MSDU_ID):
        if len(id) >= 2:
            msdu_id, = struct.unpack_from('<H', id);
            id = id[2:]
            msdu_len = msdu_len_tbl[msdu_id]
        else:
            msdu_len = 0
        output_write(struct.pack('H', msdu_len))

def ath10k_htt_pktlog_handler(pevent, trace_seq, event):
    buf = event['pktlog'].data
    offset = 0

    hdr = Ath10kPktlogHdr()
    hdr.unpack(buf, offset)
    offset = offset + hdr.hdr_len

    trace_seq.puts('%s\n' % (hdr))

    if hdr.log_type == ATH10K_PKTLOG_TYPE_TX_FRM_HDR:
        pktlog_tx_frm_hdr(buf[Ath10kPktlogHdr.hdr_len:])
    elif hdr.log_type == ATH10K_PKTLOG_TYPE_TX_CTRL:
        pktlog_tx_ctrl(buf)
    elif hdr.log_type == ATH10K_PKTLOG_TYPE_TX_MSDU_ID:
        pktlog_tx_msdu_id(buf)
    elif hdr.log_type == ATH10K_PKTLOG_TYPE_TX_STAT or \
            hdr.log_type == ATH10K_PKTLOG_TYPE_RX_STAT or \
            hdr.log_type == ATH10K_PKTLOG_TYPE_RC_FIND or \
            hdr.log_type == ATH10K_PKTLOG_TYPE_RC_UPDATE:
        output_write(buf[0 : offset + hdr.size])
    else:
        pass

def ath10k_htt_rx_desc_handler(pevent, trace_seq, event):
    tsf = long(event['tsf'])
    rxdesc = event['rxdesc'].data

    trace_seq.puts('tsf %d len %d\n' % (tsf, len(rxdesc)))

    hdr = Ath10kPktlogHdr()
    hdr.flags = (1 << ATH10K_PKTLOG_FLG_TYPE_REMOTE_S)
    hdr.missed_cnt = 0
    hdr.log_type = ATH10K_PKTLOG_TYPE_RX_STAT
    hdr.size = len(rxdesc)
    hdr.timestamp = tsf

    output_write(hdr.pack())
    output_write(rxdesc)

def ath10k_htt_tx_handler(pevent, trace_seq, event):
    global msdu_len_tbl
    msdu_id = long(event['msdu_id'])
    msdu_len = long(event['msdu_len'])

    trace_seq.puts('msdu_id %d msdu_len %d\n' % (msdu_id, msdu_len))

    if msdu_id > TARGET_NUM_MSDU_DESC:
        dbg('Invalid msdu_id in tx: %d' % (msdu_id))
        return

    msdu_len_tbl[msdu_id] = msdu_len

def ath10k_txrx_tx_unref_handler(pevent, trace_seq, event):
    global msdu_len_tbl
    msdu_id = long(event['msdu_id'])

    trace_seq.puts('msdu_id %d\n' % (msdu_id))

    if msdu_id > TARGET_NUM_MSDU_DESC:
        dbg('Invalid msdu_id from unref: %d' % (msdu_id))
        return

    msdu_len_tbl[msdu_id] = 0

def ath10k_tx_hdr_handler(pevent, trace_seq, event):
    buf = event['data'].data

    pktlog_tx_frm_hdr(buf[0:])

def register(pevent):

    output_open()

    pevent.register_event_handler("ath10k", "ath10k_htt_pktlog",
                                  lambda *args:
                                      ath10k_htt_pktlog_handler(pevent, *args))
    pevent.register_event_handler("ath10k", "ath10k_htt_rx_desc",
                                  lambda *args:
                                      ath10k_htt_rx_desc_handler(pevent, *args))
    pevent.register_event_handler("ath10k", "ath10k_htt_tx",
                                  lambda *args:
                                      ath10k_htt_tx_handler(pevent, *args))
    pevent.register_event_handler("ath10k", "ath10k_txrx_tx_unref",
                                  lambda *args:
                                      ath10k_txrx_tx_unref_handler(pevent, *args))
    pevent.register_event_handler("ath10k", "ath10k_tx_hdr",
                                  lambda *args:
                                      ath10k_tx_hdr_handler(pevent, *args))