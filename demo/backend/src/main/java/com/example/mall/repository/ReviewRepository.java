package com.example.mall.repository;

import com.example.mall.entity.Review;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.sql.PreparedStatement;
import java.util.List;

/**
 * 评价数据访问(H2 + JdbcTemplate)
 */
@Repository
public class ReviewRepository {

    private final JdbcTemplate jdbc;

    @Autowired
    public ReviewRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<Review> ROW_MAPPER = (rs, i) -> {
        Review r = new Review();
        r.setId(rs.getLong("id"));
        r.setUserId(rs.getLong("user_id"));
        r.setOrderId(rs.getLong("order_id"));
        r.setProductId(rs.getLong("product_id"));
        r.setRating(rs.getInt("rating"));
        r.setContent(rs.getString("content"));
        r.setCreatedAt(rs.getObject("created_at") == null ? null : rs.getTimestamp("created_at").toString());
        return r;
    };

    public Long insert(Review review) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update(conn -> {
            PreparedStatement ps = conn.prepareStatement(
                    "INSERT INTO review (user_id, order_id, product_id, rating, content) VALUES (?, ?, ?, ?, ?)",
                    new String[]{"id"});
            ps.setLong(1, review.getUserId());
            ps.setLong(2, review.getOrderId());
            ps.setLong(3, review.getProductId());
            ps.setInt(4, review.getRating());
            ps.setString(5, review.getContent());
            return ps;
        }, keyHolder);
        Number key = keyHolder.getKey();
        return key == null ? null : key.longValue();
    }

    /** 某商品的评价总数(用于计算平均分) */
    public int countByProduct(Long productId) {
        Integer c = jdbc.queryForObject("SELECT COUNT(*) FROM review WHERE product_id = ?", Integer.class, productId);
        return c == null ? 0 : c;
    }

    /** 某商品的平均评分(1-5) */
    public BigDecimal avgRatingByProduct(Long productId) {
        List<BigDecimal> list = jdbc.queryForList(
                "SELECT AVG(rating) FROM review WHERE product_id = ?", BigDecimal.class, productId);
        return list.isEmpty() || list.get(0) == null ? null : list.get(0);
    }

    /** 某商品的评价列表(JOIN 用户昵称,按时间倒序) */
    public List<Review> listByProduct(Long productId) {
        return jdbc.query(
                "SELECT r.*, u.nickname AS user_nickname FROM review r " +
                        "JOIN app_user u ON r.user_id = u.id " +
                        "WHERE r.product_id = ? ORDER BY r.id DESC",
                (rs, i) -> {
                    Review r = new Review();
                    r.setId(rs.getLong("id"));
                    r.setUserId(rs.getLong("user_id"));
                    r.setOrderId(rs.getLong("order_id"));
                    r.setProductId(rs.getLong("product_id"));
                    r.setRating(rs.getInt("rating"));
                    r.setContent(rs.getString("content"));
                    r.setUserNickname(rs.getString("user_nickname"));
                    r.setCreatedAt(rs.getObject("created_at") == null ? null : rs.getTimestamp("created_at").toString());
                    return r;
                }, productId);
    }
}
