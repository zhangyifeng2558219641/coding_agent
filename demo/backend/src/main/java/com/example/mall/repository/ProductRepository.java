package com.example.mall.repository;

import com.example.mall.entity.Product;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.sql.PreparedStatement;
import java.util.ArrayList;
import java.util.List;

/**
 * 商品数据访问(H2 + JdbcTemplate)
 */
@Repository
public class ProductRepository {

    private final JdbcTemplate jdbc;

    @Autowired
    public ProductRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<Product> ROW_MAPPER = (rs, i) -> {
        Product p = new Product();
        p.setId(rs.getLong("id"));
        p.setName(rs.getString("name"));
        p.setCategory(rs.getString("category"));
        p.setDescription(rs.getString("description"));
        p.setImageUrl(rs.getString("image_url"));
        p.setPrice(rs.getBigDecimal("price"));
        p.setStock(rs.getInt("stock"));
        p.setSales(rs.getInt("sales"));
        p.setAvgRating(rs.getBigDecimal("avg_rating"));
        p.setStatus(rs.getString("status"));
        p.setCreatedAt(rs.getObject("created_at") == null ? null : rs.getTimestamp("created_at").toString());
        p.setUpdatedAt(rs.getObject("updated_at") == null ? null : rs.getTimestamp("updated_at").toString());
        return p;
    };

    /**
     * 用户端商品列表:仅上架,支持分类、关键词、排序。
     * sortField 白名单:price / sales / rating(映射到 avg_rating)
     */
    public List<Product> listOnSale(String category, String keyword, String sortField, String order) {
        StringBuilder sql = new StringBuilder("SELECT * FROM product WHERE status = 'ON_SALE'");
        List<Object> args = new ArrayList<>();
        if (category != null && !category.isBlank()) {
            sql.append(" AND category = ?");
            args.add(category.trim());
        }
        if (keyword != null && !keyword.isBlank()) {
            sql.append(" AND (name LIKE ? OR description LIKE ?)");
            String like = "%" + keyword.trim() + "%";
            args.add(like);
            args.add(like);
        }

        String column = switch (sortField == null ? "" : sortField) {
            case "price" -> "price";
            case "sales" -> "sales";
            case "rating" -> "avg_rating";
            default -> "id";
        };
        String direction = "asc".equalsIgnoreCase(order) ? "ASC" : "DESC";

        // 按评分排序时,无评分(NULL)排到最后
        if ("avg_rating".equals(column)) {
            sql.append(" ORDER BY (avg_rating IS NULL) ").append(direction).append(", avg_rating ").append(direction);
        } else {
            sql.append(" ORDER BY ").append(column).append(" ").append(direction);
        }
        sql.append(", id ASC");

        return jdbc.query(sql.toString(), ROW_MAPPER, args.toArray());
    }

    /** 管理端:全部商品(含下架) */
    public List<Product> listAll() {
        return jdbc.query("SELECT * FROM product ORDER BY id", ROW_MAPPER);
    }

    public List<String> listCategories() {
        return jdbc.queryForList("SELECT DISTINCT category FROM product WHERE category IS NOT NULL AND category <> '' ORDER BY category", String.class);
    }

    public Product findById(Long id) {
        List<Product> list = jdbc.query("SELECT * FROM product WHERE id = ?", ROW_MAPPER, id);
        return list.isEmpty() ? null : list.get(0);
    }

    public Long insert(Product p) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update(conn -> {
            PreparedStatement ps = conn.prepareStatement(
                    "INSERT INTO product (name, category, description, image_url, price, stock, sales, avg_rating, status) " +
                            "VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?)",
                    new String[]{"id"});
            ps.setString(1, p.getName());
            ps.setString(2, p.getCategory());
            ps.setString(3, p.getDescription());
            ps.setString(4, p.getImageUrl());
            ps.setBigDecimal(5, p.getPrice());
            ps.setInt(6, p.getStock());
            ps.setString(7, p.getStatus());
            return ps;
        }, keyHolder);
        Number key = keyHolder.getKey();
        return key == null ? null : key.longValue();
    }

    public int update(Product p) {
        return jdbc.update("UPDATE product SET name = ?, category = ?, description = ?, image_url = ?, " +
                        "price = ?, stock = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                p.getName(), p.getCategory(), p.getDescription(), p.getImageUrl(),
                p.getPrice(), p.getStock(), p.getId());
    }

    public int updateStatus(Long id, String status) {
        return jdbc.update("UPDATE product SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", status, id);
    }

    public int count() {
        Integer c = jdbc.queryForObject("SELECT COUNT(*) FROM product", Integer.class);
        return c == null ? 0 : c;
    }

    /** 扣减库存 / 增加销量(下单用,事务内执行) */
    public int deductStockAndAddSales(Long id, int quantity) {
        return jdbc.update("UPDATE product SET stock = stock - ?, sales = sales + ?, updated_at = CURRENT_TIMESTAMP " +
                "WHERE id = ? AND stock >= ?", quantity, quantity, id, quantity);
    }

    /** 恢复库存 / 扣减销量(取消订单用) */
    public int restoreStockAndReduceSales(Long id, int quantity) {
        return jdbc.update("UPDATE product SET stock = stock + ?, sales = sales - ?, updated_at = CURRENT_TIMESTAMP " +
                "WHERE id = ? AND sales >= ?", quantity, quantity, id, quantity);
    }

    /** 更新平均评分(评价后重算) */
    public int updateAvgRating(Long id, java.math.BigDecimal avgRating) {
        return jdbc.update("UPDATE product SET avg_rating = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", avgRating, id);
    }
}
