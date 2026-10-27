"""Checks that version strings stay on their own row."""

from __future__ import annotations

import unittest

from mentions.match import find_variants


class MatchTests(unittest.TestCase):
    def test_pi_versions_do_not_collapse(self):
        self.assertEqual(find_variants("we fine-tune pi0.5 on DROID"), {"pi05"})
        self.assertEqual(find_variants("we fine-tune π0.5 on DROID"), {"pi05"})
        self.assertEqual(find_variants(r"the $\pi_{0.5}$ model"), {"pi05"})
        self.assertEqual(find_variants("π 0.5 \\pi_{0.5} cleans a kitchen"), {"pi05"})
        self.assertEqual(find_variants("compared with π0"), {"pi0"})
        self.assertEqual(find_variants("compared with π₀"), {"pi0"})
        # Bare pi0 and policy subscripts are control notation, not the model,
        # unless a nearby cue says this is the VLA.
        self.assertEqual(find_variants("compared with pi0"), set())
        self.assertEqual(find_variants(r"initial policy parameters $\pi_{0}$"), set())
        self.assertEqual(
            find_variants("we fine-tune the pi0 VLA from Physical Intelligence"),
            {"pi0"},
        )
        self.assertEqual(
            find_variants(r"the $\pi_{0}$ vision-language-action model"),
            {"pi0"},
        )
        self.assertEqual(find_variants(r"plans \pi_{0}, \pi_{1}"), set())
        self.assertEqual(find_variants(r"0 < \omega \leq 2\pi rad/s, 0 < a"), set())
        self.assertEqual(find_variants("2π 0 < a ≤ 100"), set())
        self.assertEqual(find_variants("angle of 2π-0.5"), set())
        self.assertEqual(
            find_variants("π0.5 improves on π0 and π0-FAST"),
            {"pi05", "pi0", "pi0_fast"},
        )
        self.assertEqual(find_variants("π*0.6 uses RECAP"), {"pi06_star"})
        self.assertNotIn("pi0", find_variants("only pi0.6 is discussed"))
        self.assertNotIn("pi06", find_variants("only π*0.6 is discussed"))

    def test_gr00t_versions(self):
        self.assertEqual(find_variants("GR00T N1.5 beats GR00T N1"), {"gr00t_n1_5", "gr00t_n1"})
        self.assertEqual(find_variants("we use GR00T N1.7"), {"gr00t_n1_7"})
        self.assertEqual(find_variants("the GR00T policy"), {"gr00t_unspecified"})
        self.assertNotIn("gr00t_n1", find_variants("only GR00T N1.6"))
        self.assertNotIn("gr00t_unspecified", find_variants("only GR00T N1.6"))

    def test_rt_and_openvla_versions(self):
        self.assertEqual(find_variants("RT-2-X and RT-1-X"), {"rt2_x", "rt1_x"})
        self.assertEqual(find_variants("the RT-2 model"), {"rt2"})
        self.assertNotIn("rt2", find_variants("only RT-2-X"))
        self.assertEqual(find_variants("OpenVLA-OFT"), {"openvla_oft"})
        self.assertEqual(
            find_variants("OpenVLA and OpenVLA-OFT"),
            {"openvla", "openvla_oft"},
        )

    def test_ordinary_words_do_not_match(self):
        self.assertEqual(find_variants("an octopus in the ocean"), set())
        self.assertEqual(find_variants("we act on the observation"), set())
        self.assertEqual(find_variants("a fast tokenizer is not enough"), set())
        self.assertIn("fast_tokenizer", find_variants("the FAST action tokenizer"))
        self.assertEqual(find_variants("rendered as π 0.5 without tex"), {"pi05"})
        self.assertIn("act", find_variants("Action Chunking with Transformers"))
        self.assertIn("octo", find_variants("the Octo policy"))

    def test_html_double_encoding_counts_once(self):
        text = "π 0.5 \\pi_{0.5} : a Vision-Language-Action Model. The π 0.5 model."
        self.assertEqual(find_variants(text), {"pi05"})


if __name__ == "__main__":
    unittest.main()
