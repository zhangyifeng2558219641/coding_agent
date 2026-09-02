package com.example.mall.repository;

import com.example.mall.dto.CartItemView;
import com.example.mall.entity.CartItem;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;

import java.sql.PreparedStatement;
import java.util.List;

/**
 * 购物车数据访问(H2 + JdbcTemplate)
 */
@Repository
public class CartRepository {

    private final JdbcTemplate jdbc;

    @Autowired
    public CartRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<CartItem> ITEM_MAPPER = (rs, i) -> {
        CartItem c = new CartItem();
        c.setId(rs.getLong("id"));
        c.setUserId(rs.getLong("user_id"));
        c.setProductId(rs.getLong("product_id"));
        c.setQuantity(rs.getInt("quantity"));
        c.setCreatedAt(rs.getObject("created_at") == null ? null : rs.getTimestamp("created_at").toString());
        return c;
    };

    /** 购物车列表(联查商品信息) */
    public List<CartItemView> listByUser(Long userId) {
        return jdbc.query(
                "SELECT c.id AS cart_item_id, c.quantity, p.id AS product_id, p.name AS product_name, " +
                        "p.image_url, p.price, p.stock, p.status " +
                        "FROM cart_item c JOIN product p ON c.product_id = p.id " +
                        "WHERE c.user_id = ? ORDER BY c.id",
                (rs, i) -> {
                    CartItemView v = new CartItemView();
                    v.setCartItemId(rs.getLong("cart_item_id"));
                    v.setProductId(rs.getLong("product_id"));
                    v.setProductName(rs.getString("product_name"));
                    v.setImageUrl(rs.getString("image_url"));
                    v.setPrice(rs.getBigDecimal("price"));
                    v.setQuantity(rs.getInt("quantity"));
                    v.setStock(rs.getInt("stock"));
                    v.setStatus(rs.getString("status"));
                    v.setSubtotal(rs.getBigDecimal("price").multiply(
                            java.math.BigDecimal.valueOf(rs.getInt("quantity"))));
                    return v;
                }, userId);
    }

    /** 查询某用户购物车中指定商品项(用于判断是否已存在) */
    public CartItem findByUserAndProduct(Long userId, Long productId) {
        List<CartItem> list = jdbc.query(
                "SELECT * FROM cart_item WHERE user_id = ? AND product_id = ?",
                ITEM_MAPPER, userId, productId);
        return list.isEmpty() ? null : list.get(0);
    }

    public Long insert(Long userId, Long productId, int quantity) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update(conn -> {
            PreparedStatement ps = conn.prepareStatement(
                    "INSERT INTO cart_item (user_id, product_id, quantity) VALUES (?, ?, ?)",
                    new String[]{"id"});
            ps.setLong(1, userId);
            ps.setLong(2, productId);
            ps.setInt(3, quantity);
            return ps;
        }, keyHolder);
        Number key = keyHolder.getKey();
        return key == null ? null : key.longValue();
    }

    public int updateQuantity(Long id, int quantity) {
        return jdbc.update("UPDATE cart_item SET quantity = ? WHERE id = ?", quantity, id);
    }

    public int delete(Long id) {
        return jdbc.update("DELETE FROM cart_item WHERE id = ?", id);
    }

    public int deleteByUser(Long userId) {
        return jdbc.update("DELETE FROM cart_item WHERE user_id = ?", userId);
    }

    /** 校验购物车项归属 */
    public CartItem findByIdAndUser(Long id, Long userId) {
        List<CartItem> list = jdbc.query(
                "SELECT * FROM cart_item WHERE id = ? AND user_id = ?", ITEM_MAPPER, id, userId);
        return list.isEmpty() ? null : list.get(0);
    }

    /** 批量查询指定购物车项(结算用,校验归属) */
    public List<CartItem> findByIdsAndUser(Long userId, List<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            return List.of();
        }
        String placeholders = String.join(",", java.util.Collections.nCopies(ids.size(), "?"));
        List<Object> args = new java.util.ArrayList<>();
        args.add(userId);
        args.addAll(ids);
        return jdbc.query("SELECT * FROM cart_item WHERE user_id = ? AND id IN (" + placeholders + ")",
                ITEM_MAPPER, args.toArray());
    }

    /** 批量删除购物车项(结算成功后) */
    public int deleteByUserAndIds(Long userId, List<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            return 0;
        }
        String placeholders = String.join(",", java.util.Collections.nCopies(ids.size(), "?"));
        List<Object> args = new java.util.ArrayList<>();
        args.add(userId);
        args.addAll(ids);
        return jdbc.update("DELETE FROM cart_item WHERE user_id = ? AND id IN (" + placeholders + ")", args.toArray());
    }
}
