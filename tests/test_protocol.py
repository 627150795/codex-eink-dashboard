import unittest

from PIL import Image

from codex_eink.protocol import build_bw_packets, build_bwr_packets, build_image_payload, pack_monochrome


class ProtocolTests(unittest.TestCase):
    def test_pack_monochrome_msb_first(self):
        image = Image.new("1", (8, 1), 1)
        for x in (0, 2, 7):
            image.putpixel((x, 0), 0)
        self.assertEqual(pack_monochrome(image), bytes([0b10100001]))

    def test_supported_payload_has_vendor_header_and_row_padding(self):
        image = Image.new("1", (212, 104), 1)
        image.putpixel((0, 0), 0)
        payload = build_image_payload(image)
        self.assertEqual(payload[:5], bytes([0x00, 0xD4, 0x68, 0x00, 0x00]))
        self.assertEqual(payload[5], 0x80)
        self.assertEqual(len(payload), 5 + (216 * 104 // 8))

    def test_packets_alternate_chunk_commands_and_commit(self):
        image = Image.new("1", (212, 104), 1)
        packets = build_bw_packets(image, image_index=0)
        self.assertEqual([packet[0] for packet in packets[:4]], [0x60, 0x61, 0x60, 0x61])
        self.assertEqual(packets[-1][:2], bytes([0x62, 0x00]))
        self.assertTrue(all(len(packet) == 129 for packet in packets))
        self.assertEqual(packets[-2][-1], 0xFF)

    def test_vendor_always_emits_chunk_pairs(self):
        image = Image.new("1", (250, 122), 1)
        packets = build_bw_packets(image)
        self.assertEqual(len(packets[:-1]), 32)
        self.assertEqual(packets[-2], bytes([0x61]) + b"\xFF" * 128)

    def test_packet_counts_match_vendor_for_every_profile(self):
        expected_bw = {(212, 104): 23, (250, 122): 33, (296, 128): 39, (400, 300): 119}
        expected_bwr = {(212, 104): 47, (250, 122): 67, (296, 128): 79, (400, 300): 239}
        for size in expected_bw:
            with self.subTest(size=size):
                black = Image.new("1", size, 1)
                red = Image.new("1", size, 1)
                self.assertEqual(len(build_bw_packets(black)), expected_bw[size])
                self.assertEqual(len(build_bwr_packets(black, red)), expected_bwr[size])

    def test_bwr_sequence_has_plane_markers_and_no_slot_on_commit(self):
        black = Image.new("1", (212, 104), 1)
        red = Image.new("1", (212, 104), 1)
        packets = build_bwr_packets(black, red)
        self.assertEqual(packets[0], bytes([0x5E]))
        self.assertEqual(packets[1][0], 0x60)
        marker = packets.index(bytes([0x5F]))
        self.assertEqual(packets[marker + 1][0], 0x60)
        self.assertEqual(packets[-1][0], 0x62)
        self.assertEqual(len(packets[-1]), 129)

    def test_invalid_image_size_is_rejected(self):
        with self.assertRaises(ValueError):
            build_bw_packets(Image.new("1", (320, 240), 1))


if __name__ == "__main__":
    unittest.main()
