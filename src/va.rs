//! K3 scalar arithmetic verbs translated from C to Rust.
//!
//! Based on the K3 language specification.
//! Author: Kevin Lawler
//!
//! This file contains the direct Rust translation of:
//!   times()  → _mul:  element-wise multiplication (K x * y)
//!   _dot()   → dot:   dot product / fused multiply-accumulate (+/ x * y)
//!   plus()   → plus:  element-wise addition (K x + y)
//!   minus()  → minus: element-wise subtraction (K x - y)
//!
//! Translation approach:
//!   - C macros (SCALAR_INIT, SCALAR_OP_CASE, etc.) are inlined as Rust logic
//!   - C type dispatch (if/else chains on ABS(at), ABS(bt)) preserved exactly
//!   - C void* pointer casts → Rust enum matching
//!   - C flexible array member access → Rust Vec indexing

use crate::k::{K, KData};

// ===================================================================
// SCALAR_INIT equivalent
//
// C original (from va.c, inlined macro):
//   I at=a->t, an=a->n, bt=b->t, bn=b->n;
//   I type = MAX(ABS(at),ABS(bt));
//   P(at <= 0 && bt <= 0 && an != bn, LE)
//   P(type > 2, TE);
//   I zt=type;
//   if(MIN(at,bt) < 1) zt=-zt;
//   if(!at || !bt) zt=0;
//   if(1==zt*zt)zt*=2;
//   I zn=at>0?bn:an;
//
// This computes the output type (zt) and length (zn) for a dyadic
// scalar operation, handling type promotion and scalar extension.
// ===================================================================

struct ScalarInit {
    at: i64,  // a->t
    an: i64,  // a->n
    bt: i64,  // b->t
    bn: i64,  // b->n
    zt: i64,  // output type
    zn: i64,  // output length
}

fn scalar_init(a: &K, b: &K) -> ScalarInit {
    let at = a.t;
    let an = a.n;
    let bt = b.t;
    let bn = b.n;

    // 1. Initial Type
    let typ = at.abs().max(bt.abs());

    // 2. Length Check & Logic (zn)
    // Only check strict atom mismatch here. List/Atom broadcast handled below.
    if at < 0 && bt < 0 && an != bn {
        panic!("length error: atoms mismatch");
    }
    // List mismatch strict check (if both are lists)
    if at == 0 && bt == 0 && an != bn {
        panic!("length error: lists mismatch (matrices must have same rows)");
    }
    // Broadcasting Rules: if lengths differ, one must be 1.
    // If both are > 1 and differ -> Error
    if an != bn && an != 1 && bn != 1 {
        panic!("length error: incompatible shapes an={}, bn={}", an, bn);
    }
    // Output length: max of inputs
    let zn = std::cmp::max(an, bn);

    // 3. Output Type Logic (Depends on zn)
    let mut zt = typ;

    // If result is vector length (>1), force positive type
    if zn > 1 {
        zt = zt.abs();
    } else {
        // If length 1:
        // Atom + Atom -> Atom (negative)
        // Vector + Atom -> Vector (positive)
        // Vector + Vector -> Vector (positive)
        if at < 0 && bt < 0 {
            zt = -zt.abs();
        } else {
            zt = zt.abs(); // Vector of length 1
        }
    }

    // List override (t=0)
    if at == 0 || bt == 0 {
        zt = 0;
    }

    // NOTE: K3's SCALAR_INIT(c) only promotes int→float when c==zt*zt.
    // For times/plus/minus, c=2 so 1*1=1≠2 → no promotion.
    // For divide, c=1 so 1*1=1==1 → promotes (because 5/2=2.5).
    // Promotion is handled per-verb, not globally here.
    
    assert!(zt.abs() <= 2, "type error produced invalid type");

    ScalarInit { at, an, bt, bn, zt, zn }
}

// ===================================================================
// Element-wise scalar operation helper
//
// This replaces the C SCALAR_OP_CASE macro.
// C original:
//   if(2==ABS(at)&&2==ABS(bt)){ SCALAR_OP_CASE(OP,kF(z),kF(a),kF(b)) }
//   else if(2==ABS(at)&&1==ABS(bt)){ SCALAR_OP_CASE(OP_FI,kF(z),kF(a),kI(b)) }
//   ...
//
// SCALAR_OP_CASE expands to a loop:
//   if(an==bn)      DO(zn, z[i] = OP(a[i], b[i]))
//   else if(an==1)  DO(zn, z[i] = OP(a[0], b[i]))
//   else            DO(zn, z[i] = OP(a[i], b[0]))
// ===================================================================

/// Apply a dyadic scalar operation element-wise, with scalar extension.
///
/// This is the Rust equivalent of the K3 SCALAR_OP_CASE macro.
/// Handles three cases:
///   - Both arrays same length: zip and apply
///   - a is scalar: broadcast a[0] across b
///   - b is scalar: broadcast b[0] across a
fn scalar_op_f64(
    a: &[f64],
    b: &[f64],
    an: i64,
    bn: i64,
    zn: i64,
    op: fn(f64, f64) -> f64,
) -> Vec<f64> {
    let zn = zn as usize;
    let mut z = Vec::with_capacity(zn);

    if an == bn {
        // DO(zn, z[i] = OP(a[i], b[i]))
        for i in 0..zn {
            z.push(op(a[i], b[i]));
        }
    } else if an == 1 {
        // DO(zn, z[i] = OP(a[0], b[i]))
        let a0 = a[0];
        for i in 0..zn {
            z.push(op(a0, b[i]));
        }
    } else {
        // DO(zn, z[i] = OP(a[i], b[0]))
        let b0 = b[0];
        for i in 0..zn {
            z.push(op(a[i], b0));
        }
    }
    z
}

fn scalar_op_i64(
    a: &[i64],
    b: &[i64],
    an: i64,
    bn: i64,
    zn: i64,
    op: fn(i64, i64) -> i64,
) -> Vec<i64> {
    let zn = zn as usize;
    let mut z = Vec::with_capacity(zn);

    if an == bn {
        for i in 0..zn {
            z.push(op(a[i], b[i]));
        }
    } else if an == 1 {
        let a0 = a[0];
        for i in 0..zn {
            z.push(op(a0, b[i]));
        }
    } else {
        let b0 = b[0];
        for i in 0..zn {
            z.push(op(a[i], b0));
        }
    }
    z
}

// ===================================================================
// Generic dyadic scalar verb dispatcher
//
// This replaces the entire if/else type-dispatch chain in va.c.
// Every arithmetic verb (plus, minus, times, etc.) follows the same
// pattern: SCALAR_INIT, then dispatch by type pair, create result K.
// ===================================================================

fn dyadic_scalar(
    a: &K,
    b: &K,
    op_ii: fn(i64, i64) -> i64,
    op_ff: fn(f64, f64) -> f64,
    _op_fi: fn(f64, i64) -> f64,
    _op_if: fn(i64, f64) -> f64,
) -> K {
    let s = scalar_init(a, b);

    let abs_at = s.at.abs();
    let abs_bt = s.bt.abs();

    // ---------------------------------------------------------------
    // Type dispatch — direct translation of va.c's if/else chain:
    //
    //   if(2==ABS(at)&&2==ABS(bt))      → float × float
    //   else if(2==ABS(at)&&1==ABS(bt)) → float × int
    //   else if(1==ABS(at)&&2==ABS(bt)) → int × float
    //   else if(1==ABS(at)&&1==ABS(bt)) → int × int
    //   else if(0==at||0==bt)           → general list (recurse)
    // ---------------------------------------------------------------

    if abs_at == 2 && abs_bt == 2 {
        // float × float → float
        let af = a.kf_data();
        let bf = b.kf_data();
        let zf = scalar_op_f64(af, bf, s.an, s.bn, s.zn, op_ff);
        K { t: s.zt, n: s.zn, data: KData::Floats(zf) }
    } else if abs_at == 2 && abs_bt == 1 {
        // float × int → float (C: TIMES_FI(x,y) = x * I2F(y))
        let af = a.kf_data();
        let bi = b.ki_data();
        let zf = scalar_op_f64(
            af,
            // C does I2F inline; we pre-convert. Same result.
            &bi.iter().map(|&x| K::i2f(x)).collect::<Vec<f64>>(),
            s.an, s.bn, s.zn,
            op_ff,
        );
        K { t: s.zt, n: s.zn, data: KData::Floats(zf) }
    } else if abs_at == 1 && abs_bt == 2 {
        // int × float → float (C: TIMES_IF(x,y) = I2F(x) * y)
        let ai = a.ki_data();
        let bf = b.kf_data();
        let zf = scalar_op_f64(
            &ai.iter().map(|&x| K::i2f(x)).collect::<Vec<f64>>(),
            bf,
            s.an, s.bn, s.zn,
            op_ff,
        );
        K { t: s.zt, n: s.zn, data: KData::Floats(zf) }
    } else if abs_at == 1 && abs_bt == 1 {
        // int × int → int (C: SCALAR_OP_CASE(TIMES, kI(z), kI(a), kI(b)))
        let ai = a.ki_data();
        let bi = b.ki_data();
        let zi = scalar_op_i64(ai, bi, s.an, s.bn, s.zn, op_ii);
        K { t: s.zt, n: s.zn, data: KData::Ints(zi) }
    } else if s.at == 0 || s.bt == 0 {
        // General list recursion
        // If a is list, b is atom: map over a
        match (&a.data, &b.data) {
            (KData::List(la), _) if s.at == 0 && s.bt != 0 => {
                 let new_list = la.iter().map(|item| dyadic_scalar(item, b, op_ii, op_ff, _op_fi, _op_if)).collect();
                 K::from_list(new_list)
            },
            (_, KData::List(lb)) if s.at != 0 && s.bt == 0 => {
                 let new_list = lb.iter().map(|item| dyadic_scalar(a, item, op_ii, op_ff, _op_fi, _op_if)).collect();
                 K::from_list(new_list)
            },
            (KData::List(la), KData::List(lb)) => {
                 if la.len() != lb.len() { panic!("length mismatch in recursion"); }
                 let new_list = la.iter().zip(lb.iter())
                     .map(|(item_a, item_b)| dyadic_scalar(item_a, item_b, op_ii, op_ff, _op_fi, _op_if))
                     .collect();
                 K::from_list(new_list)
            },
            _ => panic!("recursion unreachable state"),
        }
    } else {
        panic!("type error: unsupported types at={}, bt={}", s.at, s.bt);
    }
}

// ===================================================================
// times() — element-wise multiplication (_mul)
//
// C original (va.c):
//   K times(K a, K b)
//   {
//     SCALAR_INIT(2)
//     K z=newK(zt,zn);U(z)
//     #define TIMES(x, y) ((x) * (y))
//     #define TIMES_FI(x, y) ((x) * I2F(y))
//     #define TIMES_IF(x, y) (I2F(x) * (y))
//     if(2==ABS(at)&&2==ABS(bt)){ SCALAR_OP_CASE(TIMES,   kF(z),kF(a),kF(b)) }
//     else if(2==ABS(at)&&1==ABS(bt)){ SCALAR_OP_CASE(TIMES_FI,kF(z),kF(a),kI(b)) }
//     else if(1==ABS(at)&&2==ABS(bt)){ SCALAR_OP_CASE(TIMES_IF,kF(z),kI(a),kF(b)) }
//     else if(1==ABS(at)&&1==ABS(bt)){ SCALAR_OP_CASE(TIMES,   kI(z),kI(a),kI(b)) }
//     else if(0==at||0==bt){ dp(&z,times,a,b); }
//     R z;
//   }
// ===================================================================

pub fn times(a: &K, b: &K) -> K {
    dyadic_scalar(
        a, b,
        |x, y| x * y,         // TIMES(x,y) = x * y  (int)
        |x, y| x * y,         // TIMES(x,y) = x * y  (float)
        |x, y| x * K::i2f(y), // TIMES_FI(x,y) = x * I2F(y)
        |x, y| K::i2f(x) * y, // TIMES_IF(x,y) = I2F(x) * y
    )
}

// ===================================================================
// _dot() — dot product / fused multiply-accumulate
//
// C original (va.c):
//   K _dot(K a,K b)
//   {
//     SCALAR_INIT(2);
//     I A=ABS(at),B=ABS(bt);
//     I accI=0;F accF=0.0;
//     #define DOT_F   accF+=x*y
//     #define DOT_FI  accF+=x*I2F(y)
//     #define DOT_IF  accF+=I2F(x)*y
//     #define DOT_I   accI+=x*y
//     if(2==A&&2==B){ F x,y; SCALAR_EXPR_CASE(DOT_F, F,kF(a),kF(b),x,y) }
//     else if(2==A&&1==B){ F x;I y; SCALAR_EXPR_CASE(DOT_FI,F,kF(a),kI(b),x,y) }
//     else if(1==A&&2==B){ I x;F y; SCALAR_EXPR_CASE(DOT_IF,F,kI(a),kF(b),x,y) }
//     else if(1==A&&1==B){ I x,y; SCALAR_EXPR_CASE(DOT_I, I,kI(a),kI(b),x,y) }
//     else if(0==A||0==B){
//       V p[]={0,(V)0x16};
//       K x,y=overDyad(0,p+2,(x=times(a,b))); cd(x);
//       R y;
//     }
//     R 1==ABS(zt)?Ki(accI):Kf(accF);
//   }
//
// Key insight: For flat numeric arrays, _dot does the multiply-accumulate
// INLINE in a single loop (accF += x * y). No intermediate array.
// This is the fused operation that maps directly to GPU FMA instructions.
//
// For general lists (t=0), it falls back to times() then overDyad() to sum.
// That's: +/ times(a,b) — multiply then reduce with plus.
// ===================================================================

pub fn dot(a: &K, b: &K) -> K {
    let s = scalar_init(a, b);

    let abs_a = s.at.abs();
    let abs_b = s.bt.abs();

    // Integer and float accumulators — exactly like the C code
    let mut acc_i: i64 = 0;
    let mut acc_f: f64 = 0.0;

    // ---------------------------------------------------------------
    // SCALAR_EXPR_CASE — differs from SCALAR_OP_CASE in that it
    // accumulates into a scalar instead of writing to an output array.
    //
    // C pattern:
    //   SCALAR_EXPR_CASE(DOT_F, F, kF(a), kF(b), x, y)
    // expands to (approximately):
    //   if(an==bn)     DO(zn, x=kF(a)[i]; y=kF(b)[i]; accF+=x*y)
    //   else if(an==1) DO(zn, x=kF(a)[0]; y=kF(b)[i]; accF+=x*y)
    //   else           DO(zn, x=kF(a)[i]; y=kF(b)[0]; accF+=x*y)
    // ---------------------------------------------------------------

    if abs_a == 2 && abs_b == 2 {
        // float × float → float accumulator
        // DOT_F: accF += x * y
        let af = a.kf_data();
        let bf = b.kf_data();
        let n = s.zn as usize;

        if s.an == s.bn {
            for i in 0..n {
                acc_f += af[i] * bf[i]; // DOT_F
            }
        } else if s.an == 1 {
            let a0 = af[0];
            for i in 0..n {
                acc_f += a0 * bf[i]; // DOT_F
            }
        } else {
            let b0 = bf[0];
            for i in 0..n {
                acc_f += af[i] * b0; // DOT_F
            }
        }
        K::kf(acc_f)
    } else if abs_a == 2 && abs_b == 1 {
        // float × int → float accumulator
        // DOT_FI: accF += x * I2F(y)
        let af = a.kf_data();
        let bi = b.ki_data();
        let n = s.zn as usize;

        if s.an == s.bn {
            for i in 0..n {
                acc_f += af[i] * K::i2f(bi[i]); // DOT_FI
            }
        } else if s.an == 1 {
            let a0 = af[0];
            for i in 0..n {
                acc_f += a0 * K::i2f(bi[i]); // DOT_FI
            }
        } else {
            let b0 = K::i2f(bi[0]);
            for i in 0..n {
                acc_f += af[i] * b0; // DOT_FI
            }
        }
        K::kf(acc_f)
    } else if abs_a == 1 && abs_b == 2 {
        // int × float → float accumulator
        // DOT_IF: accF += I2F(x) * y
        let ai = a.ki_data();
        let bf = b.kf_data();
        let n = s.zn as usize;

        if s.an == s.bn {
            for i in 0..n {
                acc_f += K::i2f(ai[i]) * bf[i]; // DOT_IF
            }
        } else if s.an == 1 {
            let a0 = K::i2f(ai[0]);
            for i in 0..n {
                acc_f += a0 * bf[i]; // DOT_IF
            }
        } else {
            let b0 = bf[0];
            for i in 0..n {
                acc_f += K::i2f(ai[i]) * b0; // DOT_IF
            }
        }
        K::kf(acc_f)
    } else if abs_a == 1 && abs_b == 1 {
        // int × int → int accumulator
        // DOT_I: accI += x * y
        let ai = a.ki_data();
        let bi = b.ki_data();
        let n = s.zn as usize;

        if s.an == s.bn {
            for i in 0..n {
                acc_i += ai[i] * bi[i]; // DOT_I
            }
        } else if s.an == 1 {
            let a0 = ai[0];
            for i in 0..n {
                acc_i += a0 * bi[i]; // DOT_I
            }
        } else {
            let b0 = bi[0];
            for i in 0..n {
                acc_i += ai[i] * b0; // DOT_I
            }
        }
        K::ki(acc_i)
    } else if abs_a == 0 || abs_b == 0 {
        // General list fallback:
        //   C: y = overDyad(0, p+2, (x = times(a,b)));
        //   This is: +/ times(a,b) — multiply then sum
        let product = times(a, b);
        // Sum the product array (overDyad with plus)
        match &product.data {
            KData::Ints(v) => K::ki(v.iter().sum()),
            KData::Floats(v) => K::kf(v.iter().sum()),
            _ => panic!("dot: cannot sum general list"),
        }
    } else {
        panic!("type error in _dot: at={}, bt={}", s.at, s.bt);
    }
}

// ===================================================================
// plus() — element-wise addition
//
// C original (va.c):
//   K plus(K a, K b)
//   {
//     SCALAR_INIT(2)
//     K z=newK(zt,zn);U(z)
//     #define PLUS(x, y) ((x) + (y))
//     #define PLUS_FI(x, y) ((x) + I2F(y))
//     #define PLUS_IF(x, y) (I2F(x) + (y))
//     ...same dispatch pattern as times...
//     R z;
//   }
// ===================================================================

#[allow(dead_code)]
pub fn plus(a: &K, b: &K) -> K {
    dyadic_scalar(
        a, b,
        |x, y| x + y,         // PLUS(x,y) = x + y  (int)
        |x, y| x + y,         // PLUS(x,y) = x + y  (float)
        |x, y| x + K::i2f(y), // PLUS_FI(x,y) = x + I2F(y)
        |x, y| K::i2f(x) + y, // PLUS_IF(x,y) = I2F(x) + y
    )
}

// ===================================================================
// minus() — element-wise subtraction
//
// C original (va.c):
//   K minus(K a, K b)
//   {
//     SCALAR_INIT(2)
//     K z=newK(zt,zn);U(z)
//     #define MINUS(x, y) ((x) - (y))
//     #define MINUS_FI(x, y) ((x) - I2F(y))
//     #define MINUS_IF(x, y) (I2F(x) - (y))
//     ...same dispatch pattern as times...
//     R z;
//   }
// ===================================================================

#[allow(dead_code)]
pub fn minus(a: &K, b: &K) -> K {
    dyadic_scalar(
        a, b,
        |x, y| x - y,         // MINUS(x,y) = x - y  (int)
        |x, y| x - y,         // MINUS(x,y) = x - y  (float)
        |x, y| x - K::i2f(y), // MINUS_FI(x,y) = x - I2F(y)
        |x, y| K::i2f(x) - y, // MINUS_IF(x,y) = I2F(x) - y
    )
}
